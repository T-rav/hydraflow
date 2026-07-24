---
id: 0445
topic: gotchas
source_issue: 10411
source_phase: plan
created_at: 2026-07-24T05:57:06.014392+00:00
status: superseded
corroborations: 1
superseded_by: 0446
---

# Fleet rollup state carries optional `adr_numbers` — legacy entries read as empty, not missing

`src/state/_adr_audit.py`'s `get/set/all_adr_rollups` treats `adr_numbers` as an optional additive field (no migration): legacy `FLEET-<pr>` entries filed before this change round-trip with an empty list rather than erroring. `adr_touchpoint_auditor_loop.py` persists the member ADR numbers when filing a fleet rollup. **Why:** lets the resolver enumerate fleet members without importing `adr_drift.py` detection logic, preserving the resolver's never-edit-the-detector invariant, while keeping old rollups safely inert (one-shot human-close) instead of breaking.
