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
    def _extract_period_header_labels(self, result):
        """Extract column labels from the mis_builder result header.

        ``result['header']`` is a list of header rows; the labels of the
        periods (columns) typically live in the last header row's ``cols``.
        Returns a list of strings, one per data column.
        """
        header = result.get("header") or []
        if not header:
            return []
        # The last header row contains the most specific labels (period names)
        last_row = header[-1] if isinstance(header[-1], dict) else {}
        cols = last_row.get("cols") or []
        labels = []
        for col in cols:
            if isinstance(col, dict):
                labels.append(col.get("label") or col.get("name") or "")
            else:
                labels.append(str(col))
        return labels

    @api.model
    def _coerce_value(self, raw_val):
        """Coerce mis_builder value (possibly AccountingNone) to float."""
        if raw_val is None:
            return 0.0
        if isinstance(raw_val, (int, float)):
            return float(raw_val)
        # AccountingNone, str, etc.
        try:
            return float(raw_val)
        except (TypeError, ValueError):
            return 0.0

    @api.model
    def snapshot_instance(self, instance):
        """Compute one ``mis.report.instance`` and persist every KPI/period.

        History-preserving: never deletes prior snapshots, every call appends
        rows tagged with the current ``computed_at`` timestamp.

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

        # Build a lookup of periods by their display name for mapping cols→period
        periods_by_name = {p.name: p for p in instance.period_ids}
        ordered_periods = list(instance.period_ids)
        period_labels = self._extract_period_header_labels(result)

        now = fields.Datetime.now()
        company = instance.company_id or self.env.company
        records_to_create = []

        for row in result.get("content") or []:
            if not isinstance(row, dict):
                continue

            kpi_name = row.get("kpi_name") or row.get("row_id") or ""
            kpi_description = row.get("description") or ""
            kpi_sequence_raw = row.get("row_id") or row.get("sequence") or 0
            kpi_sequence = (
                kpi_sequence_raw if isinstance(kpi_sequence_raw, int) else 0
            )

            # Detect subtotal/total rows via style hint when available
            style = row.get("style") or {}
            is_subtotal = False
            if isinstance(style, dict):
                is_subtotal = style.get("font_weight") == "bold"

            cols = row.get("cols") or []
            for col_idx, col in enumerate(cols):
                if not isinstance(col, dict):
                    continue

                # Map column to a period: prefer header label match, fallback to index
                col_label = (
                    period_labels[col_idx]
                    if col_idx < len(period_labels)
                    else "col_{}".format(col_idx)
                )
                period = periods_by_name.get(col_label)
                if not period and col_idx < len(ordered_periods):
                    period = ordered_periods[col_idx]

                value = self._coerce_value(col.get("val"))
                value_str = col.get("val_r") or col.get("val_c") or ""
                if not value_str:
                    value_str = "{:.2f}".format(value)

                records_to_create.append(
                    {
                        "instance_id": instance.id,
                        "kpi_name": str(kpi_name),
                        "kpi_description": kpi_description,
                        "kpi_sequence": kpi_sequence,
                        "is_subtotal": is_subtotal,
                        "period_id": period.id if period else False,
                        "period_name": period.name if period else col_label,
                        "period_date_from": (
                            period.date_from if period else instance.date_from
                        ),
                        "period_date_to": (
                            period.date_to if period else instance.date_to
                        ),
                        "value": value,
                        "value_str": str(value_str),
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
