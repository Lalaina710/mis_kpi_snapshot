# Changelog

All notable changes to this module are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions adhere to Odoo 18 semantic versioning `18.0.X.Y.Z`.

## [18.0.1.0.0] - 2026-05-25

### Added
- Initial release.
- Model `mis.kpi.snapshot` — flat materialized table for KPI values.
- Extension of `mis.report.instance` with:
  - `Snapshot Now` header button
  - Smart button + `snapshot_count` / `last_snapshot_at` computed fields
- Daily cron `cron_mis_kpi_snapshot_daily` (03:00 server time).
- Wizard `mis.kpi.snapshot.all.wizard` for batch snapshots with optional
  company / report / instance filters.
- ACL: read for accountants, write for accounting managers, full for admin.
- Menus under `Accounting → Configuration → MIS Reporting → KPI Snapshots`.
