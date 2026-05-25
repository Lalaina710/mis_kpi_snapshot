# Copyright 2026 SOPROMER
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class MisKpiSnapshot(models.Model):
    """Stores one row per (instance, period, KPI) materialized result.

    Designed to be queried directly by BI tools (Metabase, Superset, etc.)
    via raw SQL: ``SELECT ... FROM mis_kpi_snapshot WHERE ...``.
    """

    _name = "mis.kpi.snapshot"
    _description = "MIS KPI Snapshot"
    _order = "computed_at desc, instance_id, kpi_sequence"
    _rec_name = "display_name"

    # --- Reference fields ----------------------------------------------------
    instance_id = fields.Many2one(
        "mis.report.instance",
        string="MIS Report Instance",
        required=True,
        ondelete="cascade",
        index=True,
        help="MIS report instance this snapshot was computed from.",
    )
    report_id = fields.Many2one(
        "mis.report",
        related="instance_id.report_id",
        store=True,
        index=True,
        help="Template referenced by the instance.",
    )
    report_name = fields.Char(
        related="instance_id.report_id.name",
        store=True,
        string="Report Template",
    )
    instance_name = fields.Char(
        related="instance_id.name",
        store=True,
        string="Instance Name",
    )

    # --- KPI fields ----------------------------------------------------------
    kpi_name = fields.Char(
        required=True,
        index=True,
        help="Technical name of the KPI (ex: marge_commerciale).",
    )
    kpi_description = fields.Char(
        string="KPI Label",
        help="Human-readable KPI label, as defined on the template.",
    )
    kpi_sequence = fields.Integer(
        default=10,
        help="KPI display order within the report.",
    )
    is_subtotal = fields.Boolean(
        default=False,
        help="True when the KPI row is a subtotal or total (bold style).",
    )

    # --- Period fields -------------------------------------------------------
    period_id = fields.Many2one(
        "mis.report.instance.period",
        string="Period",
        ondelete="cascade",
        help="Period (column) the value applies to.",
    )
    period_name = fields.Char(
        required=True,
        help="Period label (ex: 'Current Year', 'Previous Month').",
    )
    period_date_from = fields.Date(
        required=True,
        help="Start of the period (inclusive).",
    )
    period_date_to = fields.Date(
        required=True,
        help="End of the period (inclusive).",
    )

    # --- Value fields --------------------------------------------------------
    value = fields.Float(
        digits=(20, 2),
        help="Numeric value computed by mis_builder for this KPI/period.",
    )
    value_str = fields.Char(
        string="Formatted Value",
        help="Pre-formatted value as displayed in the MIS report UI.",
    )

    # --- Meta fields ---------------------------------------------------------
    company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
        default=lambda self: self.env.company,
        help="Company the snapshot relates to.",
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        store=True,
        readonly=True,
    )
    computed_at = fields.Datetime(
        required=True,
        default=fields.Datetime.now,
        index=True,
        help="Exact timestamp when the snapshot was computed.",
    )
    computed_by = fields.Many2one(
        "res.users",
        default=lambda self: self.env.user,
        readonly=True,
        help="User (or cron user) who triggered the snapshot.",
    )

    display_name = fields.Char(
        compute="_compute_display_name",
        store=False,
    )

    # ------------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------------
    @api.depends("instance_name", "period_name", "kpi_description", "computed_at")
    def _compute_display_name(self):
        for snap in self:
            snap.display_name = "{} / {} / {}".format(
                snap.instance_name or "?",
                snap.period_name or "?",
                snap.kpi_description or snap.kpi_name or "?",
            )

    # ------------------------------------------------------------------------
    # Business logic — snapshotting
    # ------------------------------------------------------------------------
    @api.model
    def _coerce_value(self, raw_val):
        """Coerce mis_builder value (possibly AccountingNone/None) to float."""
        if raw_val is None:
            return 0.0
        if isinstance(raw_val, (int, float)):
            return float(raw_val)
        try:
            return float(raw_val)
        except (TypeError, ValueError):
            return 0.0

    @api.model
    def snapshot_instance(self, instance):
        """Compute one ``mis.report.instance`` and persist every KPI/period.

        History-preserving: never deletes prior snapshots, every call appends
        rows tagged with the current ``computed_at`` timestamp.

        Compatible with mis_builder v18.0.1.8.1 result structure:
        - result['body']: list of rows, each with 'label', 'style', 'cells'
        - result['header'][0]['cols']: list of period column descriptors
        - cell['cell_id']: '<kpi_id>##<period_id>#' format
        - cell['val']: numeric value (float or None)
        - cell['val_r']: formatted value string

        Returns the number of records created.
        """
        if not instance:
            return 0
        instance.ensure_one()

        try:
            result = instance.compute()
        except Exception as e:
            _logger.exception(
                "MIS snapshot failed to compute instance %s (id=%s): %s",
                instance.name,
                instance.id,
                e,
            )
            return 0

        if not isinstance(result, dict):
            _logger.warning(
                "MIS snapshot: instance %s returned non-dict result, skipping.",
                instance.name,
            )
            return 0

        body = result.get("body") or []
        if not body:
            _logger.info(
                "MIS snapshot: instance %s returned empty body, skipping.",
                instance.name,
            )
            return 0

        # Build period lookup by id and by ordered position
        periods_by_id = {p.id: p for p in instance.period_ids}
        ordered_periods = list(instance.period_ids)

        # Build KPI lookup by id for technical name resolution
        kpi_by_id = {}
        if instance.report_id:
            for kpi in instance.report_id.kpi_ids:
                kpi_by_id[kpi.id] = kpi

        now = fields.Datetime.now()
        company = instance.company_id or self.env.company
        records_to_create = []

        for seq_idx, row in enumerate(body):
            if not isinstance(row, dict):
                continue

            kpi_description = row.get("label") or ""
            style_str = row.get("style") or ""
            is_subtotal = "font-weight: bold" in style_str

            cells = row.get("cells") or []
            for col_idx, cell in enumerate(cells):
                if not isinstance(cell, dict):
                    continue

                # Extract kpi_id and period_id from cell_id: '<kpi_id>##<period_id>#'
                cell_id = cell.get("cell_id") or ""
                kpi_name = kpi_description  # fallback
                period = None
                if cell_id and "##" in cell_id:
                    parts = cell_id.split("##")
                    try:
                        kpi_id = int(parts[0])
                        kpi_obj = kpi_by_id.get(kpi_id)
                        if kpi_obj:
                            kpi_name = kpi_obj.name
                    except (ValueError, IndexError):
                        pass
                    try:
                        period_id_str = parts[1].rstrip("#")
                        if period_id_str:
                            period = periods_by_id.get(int(period_id_str))
                    except (ValueError, IndexError):
                        pass

                # Fallback: match period by column index
                if not period and col_idx < len(ordered_periods):
                    period = ordered_periods[col_idx]

                if not period:
                    _logger.debug(
                        "MIS snapshot: no period for cell_id=%s, skipping.", cell_id
                    )
                    continue

                value = self._coerce_value(cell.get("val"))
                value_str = cell.get("val_r") or ""
                if not value_str:
                    value_str = "{:.2f}".format(value)
                # Clean non-breaking spaces from formatted values
                value_str = value_str.replace("\xa0", " ").strip()

                records_to_create.append(
                    {
                        "instance_id": instance.id,
                        "kpi_name": kpi_name or kpi_description or "kpi_{}".format(seq_idx),
                        "kpi_description": kpi_description,
                        "kpi_sequence": seq_idx,
                        "is_subtotal": is_subtotal,
                        "period_id": period.id,
                        "period_name": period.name,
                        "period_date_from": period.date_from,
                        "period_date_to": period.date_to,
                        "value": value,
                        "value_str": value_str,
                        "company_id": company.id,
                        "computed_at": now,
                    }
                )

        if not records_to_create:
            _logger.info(
                "MIS snapshot: instance %s produced 0 KPI rows (empty report?).",
                instance.name,
            )
            return 0

        snapshots = self.create(records_to_create)
        _logger.info(
            "MIS snapshot: created %d rows for instance %s (id=%s).",
            len(snapshots),
            instance.name,
            instance.id,
        )
        return len(snapshots)

    @api.model
    def snapshot_all_active_instances(self, company_ids=None, report_ids=None):
        """Cron entry point — snapshot every configured instance.

        :param company_ids: optional list of company ids to restrict snapshots
        :param report_ids:  optional list of mis.report template ids to restrict
        :returns: total number of snapshot rows created
        """
        domain = []
        if company_ids:
            domain.append(("company_id", "in", list(company_ids)))
        if report_ids:
            domain.append(("report_id", "in", list(report_ids)))

        Instance = self.env["mis.report.instance"]
        instances = Instance.search(domain)
        # Only snapshot instances with at least one configured period
        instances = instances.filtered(lambda i: i.period_ids)

        total = 0
        for inst in instances:
            try:
                total += self.snapshot_instance(inst)
            except Exception as e:
                _logger.exception(
                    "MIS snapshot: failure on instance %s (id=%s): %s",
                    inst.name,
                    inst.id,
                    e,
                )
                # Best-effort: continue with next instance, do not block the whole cron
                continue

        _logger.info(
            "MIS snapshot cron completed: %d rows across %d instances.",
            total,
            len(instances),
        )
        return total

    # ------------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------------
    def action_open_instance(self):
        """Open the source MIS report instance from a snapshot row."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("MIS Report Instance"),
            "res_model": "mis.report.instance",
            "res_id": self.instance_id.id,
            "view_mode": "form",
            "target": "current",
        }
