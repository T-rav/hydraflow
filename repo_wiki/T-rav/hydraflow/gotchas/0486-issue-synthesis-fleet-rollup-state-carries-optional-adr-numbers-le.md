---
id: 0486
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:27:31.405947+00:00
status: active
corroborations: 1
supersedes: 0402,0403,0404,0405,0406,0407,0408,0409,0410,0411,0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445
---

# Fleet rollup state carries optional `adr_numbers` — legacy entries read as empty, not missing

`src/state/_adr_audit.py`'s `get/set/all_adr_rollups` treats `adr_numbers` as an optional additive field (no migration): legacy `FLEET-<pr>` entries filed before this change round-trip with an empty list rather than erroring. `adr_touchpoint_auditor_loop.py` persists the member ADR numbers when filing a fleet rollup.

**Why:** lets the resolver enumerate fleet members without importing `adr_drift.py` detection logic, preserving the resolver's never-edit-the-detector invariant, while keeping old rollups safely inert (one-shot human-close) instead of breaking.
