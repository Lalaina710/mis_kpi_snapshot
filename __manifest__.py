# Copyright 2026 SOPROMER
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
{
    "name": "MIS KPI Snapshot",
    "version": "18.0.1.0.1",
    "category": "Accounting/Reporting",
    "summary": "Materialize KPI computed by mis_builder into a SQL table queryable by Metabase / BI tools",
    "description": """
MIS KPI Snapshot
================

Lightweight module that periodically computes ``mis.report.instance`` results
and materializes each KPI value into a flat SQL table (``mis_kpi_snapshot``)
that can be queried directly by BI tools (Metabase, Superset, PowerBI, etc.).

Features
--------
* New model ``mis.kpi.snapshot`` storing one row per (instance, period, KPI)
* Manual button ``Snapshot Now`` on every ``mis.report.instance`` form
* Daily cron auto-snapshotting all configured instances
* Wizard ``Snapshot All Instances`` with optional filters by company / report
* History preserved: every run adds new rows timestamped with ``computed_at``
* ACL: read for accountants, write for managers, full for system admin
* Generic & multi-client: no hardcoded dependency on any specific template

Use cases
---------
* Expose mis_builder KPI to Metabase dashboards (JOIN on mis_kpi_snapshot)
* Build month-over-month KPI evolution charts in any BI tool
* Audit trail of KPI values (frozen at computed_at)

Coordination
------------
Pairs naturally with the ``odoo-metabase`` workflow: grant SELECT on
``mis_kpi_snapshot`` to your reporting DB role and JOIN with other
exposed Odoo tables.
    """,
    "author": "SOPROMER",
    "website": "https://github.com/Lalaina710/mis_kpi_snapshot",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mis_builder",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/mis_kpi_snapshot_views.xml",
        "views/mis_report_instance_views.xml",
        "views/wizard_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
