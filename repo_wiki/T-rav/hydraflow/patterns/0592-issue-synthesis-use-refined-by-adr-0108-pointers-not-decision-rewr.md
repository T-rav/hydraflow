---
id: 0592
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:08:06.335597+00:00
status: active
corroborations: 1
supersedes: 0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583
---

# Use 'Refined by ADR-0108' pointers, not decision rewrites, for extended ADRs

When a new ADR extends an already-Accepted ADR's contract, add a one-line "Refined by ADR-NNNN" pointer to the older ADR instead of rewriting its decision text.

Example: ADR-0108 refines ADR-0059/0095/0102 by adding a STOP/HITL disposition; each gets an additive pointer line, keeping diffs insertion-only.

**Why:** rewriting shipped decision text can misstate flag defaults or contradict deployed behavior; `adr_cross_reference` expects links to resolve to existing files.
