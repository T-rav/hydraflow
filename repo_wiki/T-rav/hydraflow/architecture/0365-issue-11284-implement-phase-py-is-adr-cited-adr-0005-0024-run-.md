---
id: 0365
topic: architecture
source_issue: 11284
source_phase: plan
created_at: 2026-08-16T01:29:44.315671+00:00
status: active
corroborations: 1
---

# implement_phase.py is ADR-cited (ADR-0005/0024); run arch-regen and ADR-drift checks

`src/implement_phase.py` belongs to the ADR-0005/0024 recovery family and is multi-concern. Any change to flow-screening or recovery routing triggers arch-regen and ADR-drift checks. Prefer extending the wiki recovery entry over adding a new ADR unless review explicitly flags one. No new loop/runner means ADR-0049 kill-switch is N/A; use a config flag instead (e.g. `implement_salvage_reconcile_enabled`).

**Why:** Skipping ADR-drift checks on a cited file silently breaks the documented architecture contract and recovery-family consistency.
