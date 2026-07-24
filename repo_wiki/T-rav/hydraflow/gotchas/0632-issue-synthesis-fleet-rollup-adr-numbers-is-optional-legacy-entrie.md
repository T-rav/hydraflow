---
id: 0632
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:09:28.510306+00:00
status: superseded
corroborations: 1
supersedes: 0545,0546,0547,0548,0549,0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
superseded_by: 0643
---

# Fleet rollup `adr_numbers` is optional — legacy entries read as empty

`src/state/_adr_audit.py`'s `get/set/all_adr_rollups` treats `adr_numbers` as an optional additive field (no migration): legacy `FLEET-<pr>` entries filed before this change round-trip with an empty list rather than erroring.

Example: `adr_touchpoint_auditor_loop.py` persists the member ADR numbers when filing a fleet rollup.

**Why:** Lets the resolver enumerate fleet members without importing `adr_drift.py` detection logic, preserving the resolver's never-edit-the-detector invariant, while keeping old rollups safely inert (one-shot human-close) instead of breaking.
