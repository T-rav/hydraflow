---
id: 0559
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T02:20:36.845372+00:00
status: active
corroborations: 1
supersedes: 0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539,0540,0542,0543,0544,0545,0546,0547,0548,0549
---

# Use 'Refined by ADR-0108' pointers, not decision rewrites, for extended ADRs

When a new ADR extends an already-Accepted ADR's contract, add a one-line "Refined by ADR-NNNN" pointer to the older ADR instead of rewriting its decision text — mirror the existing ADR-0094↔ADR-0102 convention.

Example: ADR-0108 refines ADR-0059/0095/0102 by adding a self-modification fail-closed STOP/HITL disposition; each gets an additive pointer line, so the diff is insertion-only.

**Why:** rewriting shipped decision text can misstate flag defaults or contradict deployed behavior; `adr_cross_reference` regeneration expects Related/Refines links to resolve to existing files, so dangling or altered links fail `adr-conformance.md` CI.
