# Copyright 2026 SOPROMER
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import _, fields, models


class MisKpiSnapshotAllWizard(models.TransientModel):
    """Wizard to manually trigger snapshots on multiple instances at once."""

    _name = "mis.kpi.snapshot.all.wizard"
    _description = "MIS KPI Snapshot — Batch Wizard"

    company_ids = fields.Many2many(
        "res.company",
        string="Companies",
        default=lambda self: self.env.companies,
        help="Restrict to instances owned by these companies. "
        "Leave empty for all allowed companies.",
    )
    report_ids = fields.Many2many(
        "mis.report",
        string="Report Templates",
        help="Restrict to instances using these report templates. "
        "Leave empty to include every template.",
    )
    instance_ids = fields.Many2many(
        "mis.report.instance",
        string="Specific Instances",
        help="If set, only these instances are snapshotted "
        "(company / report filters are ignored).",
    )

    def action_run(self):
        """Run the snapshots and display a summary notification."""
        self.ensure_one()
        Snapshot = self.env["mis.kpi.snapshot"]

        if self.instance_ids:
            total = 0
            for inst in self.instance_ids:
                total += Snapshot.snapshot_instance(inst)
            instance_count = len(self.instance_ids)
        else:
            company_ids = self.company_ids.ids or None
            report_ids = self.report_ids.ids or None
            total = Snapshot.snapshot_all_active_instances(
                company_ids=company_ids,
                report_ids=report_ids,
            )
            # Count for display
            domain = []
            if company_ids:
                domain.append(("company_id", "in", company_ids))
            if report_ids:
                domain.append(("report_id", "in", report_ids))
            instance_count = self.env["mis.report.instance"].search_count(domain)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Snapshot Batch Done"),
                "message": _(
                    "%(rows)d KPI rows snapshotted across %(inst)d instance(s)."
                )
                % {"rows": total, "inst": instance_count},
                "type": "success" if total else "warning",
                "sticky": False,
            },
        }
