---
id: 0508
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T06:12:20.637934+00:00
status: active
corroborations: 1
supersedes: 0481,0482,0483,0484,0485,0486,0487,0488,0489,0490,0491,0492,0493,0494,0495,0496,0497,0498
---

# Use 'Refined by ADR-0108' pointers, not decision rewrites, for extended ADRs

When a new ADR extends an already-Accepted ADR's contract, add a one-line "Refined by ADR-NNNN" pointer to the older ADR instead of rewriting its decision text — mirror the existing ADR-0094↔ADR-0102 convention.

Example: ADR-0108 refines ADR-0059/0095/0102 by adding a self-modification fail-closed STOP/HITL disposition; each gets an additive pointer line, so the diff is insertion-only.

**Why:** rewriting shipped decision text can misstate flag defaults or contradict deployed behavior; `adr_cross_reference` regeneration also expects Related/Refines links to resolve to existing files, so dangling or altered links fail `adr-conformance.md` CI.
