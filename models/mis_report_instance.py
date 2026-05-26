# Copyright 2026 SOPROMER
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import _, api, fields, models


class MisReportInstance(models.Model):
    """Extend mis.report.instance with snapshot integration."""

    _inherit = "mis.report.instance"

    snapshot_count = fields.Integer(
        compute="_compute_snapshot_stats",
        string="Snapshots",
        help="Number of snapshot rows currently stored for this instance.",
    )
    last_snapshot_at = fields.Datetime(
        compute="_compute_snapshot_stats",
        string="Last Snapshot",
        help="Timestamp of the most recent snapshot run for this instance.",
    )

    @api.depends()
    def _compute_snapshot_stats(self):
        """Compute snapshot count + last computed_at via read_group (fast)."""
        Snapshot = self.env["mis.kpi.snapshot"]
        if not self.ids:
            for inst in self:
                inst.snapshot_count = 0
                inst.last_snapshot_at = False
            return

        groups = Snapshot.read_group(
            domain=[("instance_id", "in", self.ids)],
            fields=["instance_id", "computed_at:max", "instance_id:count"],
            groupby=["instance_id"],
        )
        stats_by_inst = {
            g["instance_id"]: (
                g.get("instance_id_count", 0),
                g.get("computed_at"),
            )
            for g in groups
        }
        for inst in self:
            count, last_at = stats_by_inst.get(inst.id, (0, False))
            inst.snapshot_count = count
            inst.last_snapshot_at = last_at

    def action_snapshot_now(self):
        """Manual button — snapshot this single instance immediately."""
        self.ensure_one()
        count = self.env["mis.kpi.snapshot"].snapshot_instance(self)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Snapshot OK"),
                "message": _("%(count)d KPI rows snapshotted for %(name)s.")
                % {"count": count, "name": self.name},
                "type": "success" if count else "warning",
                "sticky": False,
            },
        }

    def action_view_snapshots(self):
        """Smart button — open the snapshot rows for this instance."""
        self.ensure_one()
        return {
            "name": _("Snapshots — %s") % self.name,
            "type": "ir.actions.act_window",
            "res_model": "mis.kpi.snapshot",
            "view_mode": "list,form",
            "domain": [("instance_id", "=", self.id)],
            "context": {"default_instance_id": self.id},
        }
