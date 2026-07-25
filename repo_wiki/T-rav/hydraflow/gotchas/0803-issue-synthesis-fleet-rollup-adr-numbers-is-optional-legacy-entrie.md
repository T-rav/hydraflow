---
id: 0803
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:43:04.003648+00:00
status: active
corroborations: 1
supersedes: 0704,0705,0706,0707,0708,0709,0710,0711,0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753,0754,0755,0756,0757,0758,0759,0760,0761,0762
---

# Fleet rollup `adr_numbers` is optional — legacy entries read as empty

`src/state/_adr_audit.py`'s `get/set/all_adr_rollups` treats `adr_numbers` as an optional additive field (no migration): legacy `FLEET-<pr>` entries filed before this change round-trip with an empty list rather than erroring.

Example: `adr_touchpoint_auditor_loop.py` persists the member ADR numbers when filing a fleet rollup.

**Why:** Lets the resolver enumerate fleet members without importing `adr_drift.py` detection logic, preserving the resolver's never-edit-the-detector invariant, while keeping old rollups safely inert (one-shot human-close) instead of breaking.
