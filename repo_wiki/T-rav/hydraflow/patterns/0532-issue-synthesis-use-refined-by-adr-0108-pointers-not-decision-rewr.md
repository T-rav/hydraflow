---
id: 0532
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:44:03.238461+00:00
status: superseded
corroborations: 1
supersedes: 0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522
superseded_by: 0550
---

# Use 'Refined by ADR-0108' pointers, not decision rewrites, for extended ADRs

When a new ADR extends an already-Accepted ADR's contract, add a one-line "Refined by ADR-NNNN" pointer to the older ADR instead of rewriting its decision text — mirror the existing ADR-0094↔ADR-0102 convention.

Example: ADR-0108 refines ADR-0059/0095/0102 by adding a self-modification fail-closed STOP/HITL disposition; each gets an additive pointer line, so the diff is insertion-only.

**Why:** rewriting shipped decision text can misstate flag defaults or contradict deployed behavior; `adr_cross_reference` regeneration also expects Related/Refines links to resolve to existing files, so dangling or altered links fail `adr-conformance.md` CI.
