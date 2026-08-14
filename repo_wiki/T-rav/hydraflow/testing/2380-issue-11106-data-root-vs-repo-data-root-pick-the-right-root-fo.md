---
id: 2380
topic: testing
source_issue: 11106
source_phase: plan
created_at: 2026-08-14T07:39:28.346544+00:00
status: active
corroborations: 1
---

# data_root vs repo_data_root — pick the right root for each reader

Trust-fleet readers resolve paths from two distinct roots. Mixing them yields a report full of nulls that still "passes."

- `data_root`: traces (`data_root/traces/_loops/<slug>/run-*.json`), `data_root/memory/.<worker>_last_run`, `data_root/dedup/trust_fleet_sanity.json`
- `repo_data_root`: `state_file`, `event_log_path`

Build every reader from a single `HydraFlowConfig` and assert non-empty sections against seeded fixtures.

**Why:** A silently-empty report from the wrong root is worse than a crash — it looks healthy while being evidence-free.
