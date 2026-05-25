# MIS KPI Snapshot

Materialize KPI values computed by [`mis_builder`](https://github.com/OCA/mis-builder)
into a flat SQL table (`mis_kpi_snapshot`) queryable by BI tools (Metabase,
Superset, PowerBI, Grafana, etc.).

- **Odoo version**: 18.0
- **License**: LGPL-3
- **Author**: SOPROMER
- **Depends**: `base`, `mis_builder`

## Why

`mis_builder` is great for **configurable** financial reporting (Bilan, Compte
de Résultat, SIG, KPI dashboards) but its computed values live **only in
memory** — they are never persisted. BI tools that consume Odoo via SQL cannot
JOIN on KPI values out of the box.

This module bridges that gap: every snapshot run computes one
`mis.report.instance` and writes one row per `(period, KPI)` into the
`mis_kpi_snapshot` table.

```
mis.report.instance (existing, configured by accountant)
       ↓ compute() executed periodically by cron
   mis.kpi.snapshot (this module — historical results)
       ↓ JOIN SQL via metabase_reader user
   Dashboards Metabase auto-synchronized
```

## Features

- New model `mis.kpi.snapshot` (one row per instance / period / KPI)
- Button `Snapshot Now` on every `mis.report.instance` form
- Smart button `Snapshots` on the instance form (count + last run timestamp)
- Daily cron at **03:00 server time** snapshotting every configured instance
- Wizard `Snapshot All Instances` with optional filters
  (company / report / specific instances)
- History preserved: every run appends rows tagged with `computed_at`
- ACL: read for `account.group_account_invoice`, full for
  `account.group_account_manager` and `base.group_system`
- Multi-company aware (`company_id`, currency)
- Generic — no client-specific code

## Installation

1. Install the OCA dependency `mis_builder` (>= 18.0.1.8.1).
2. Copy this module into your `addons_path`.
3. Update apps list and install **MIS KPI Snapshot**.

## Usage

### Manual snapshot
1. Go to **Accounting → Configuration → MIS Reporting → MIS Report Templates**
   and open an existing instance (or create one with at least one period).
2. Click **Snapshot Now** in the header.
3. Click the **Snapshots** smart button to inspect the persisted rows.

### Automatic snapshot
The cron **MIS KPI Snapshot — Daily compute all instances** runs every day at
03:00 server time. Adjust via **Settings → Technical → Scheduled Actions**.

### Batch wizard
**Accounting → Configuration → MIS Reporting → KPI Snapshots → Snapshot All
Instances** lets you run a one-shot batch, optionally filtered by company,
report template, or specific instances.

### Querying from Metabase

```sql
SELECT
    s.computed_at::date AS snapshot_date,
    s.instance_name,
    s.period_name,
    s.kpi_description,
    s.value
FROM mis_kpi_snapshot s
WHERE s.company_id = {{company_id}}
  AND s.is_subtotal = TRUE
  AND s.computed_at >= NOW() - INTERVAL '30 days'
ORDER BY s.computed_at DESC, s.kpi_sequence;
```

Grant read access to your reporting role:

```sql
GRANT SELECT ON mis_kpi_snapshot TO metabase_reader;
```

## Table schema

| Column              | Type      | Notes                                  |
| ------------------- | --------- | -------------------------------------- |
| `id`                | int       | PK                                     |
| `instance_id`       | int       | FK `mis_report_instance` (cascade)     |
| `report_id`         | int       | FK `mis_report` (related, stored)      |
| `report_name`       | varchar   | denormalized for fast JOINs            |
| `instance_name`     | varchar   | denormalized                           |
| `kpi_name`          | varchar   | technical name (`marge_brute`)         |
| `kpi_description`   | varchar   | human label                            |
| `kpi_sequence`      | int       | display order                          |
| `is_subtotal`       | bool      | true for bold rows                     |
| `period_id`         | int       | FK `mis_report_instance_period`        |
| `period_name`       | varchar   |                                        |
| `period_date_from`  | date      |                                        |
| `period_date_to`    | date      |                                        |
| `value`             | numeric   | the materialized number                |
| `value_str`         | varchar   | pre-formatted as in mis_builder UI     |
| `company_id`        | int       | FK `res_company`                       |
| `currency_id`       | int       | FK `res_currency` (related)            |
| `computed_at`       | timestamp | when snapshot was taken                |
| `computed_by`       | int       | FK `res_users`                         |

## Limitations / Roadmap

- No automated unit tests in v18.0.1.0.0 (manual QA only).
- KPI subtotal detection relies on the `style.font_weight` heuristic — a
  template setting an explicit "is_subtotal" flag would be more robust.
- No retention policy: snapshots accumulate forever. Add a custom cron
  to prune old rows if needed (e.g. keep only the last 90 days).
- No automatic indexing beyond the default Odoo ones. For very large
  history tables, consider adding a composite index on
  `(company_id, report_id, computed_at)`.

## Bug Tracker

Issues: https://github.com/Lalaina710/mis_kpi_snapshot/issues
