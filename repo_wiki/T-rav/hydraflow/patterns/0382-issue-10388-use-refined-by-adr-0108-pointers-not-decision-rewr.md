---
id: 0382
topic: patterns
source_issue: 10388
source_phase: plan
created_at: 2026-07-24T04:39:16.271122+00:00
status: active
corroborations: 1
---

# Use 'Refined by ADR-0108' pointers, not decision rewrites, for extended ADRs

When a new ADR extends an already-Accepted ADR's contract (e.g. adding a fail-closed disposition), add a one-line "Refined by ADR-NNNN" pointer to the older ADR instead of rewriting its decision text — mirror the existing ADR-0094↔ADR-0102 convention.

Example: ADR-0108 refines ADR-0059/0095/0102 by adding a self-modification fail-closed STOP/HITL disposition; each gets an additive pointer line, diff is insertion-only.

**Why:** rewriting shipped decision text can misstate flag defaults or contradict already-deployed behavior; `adr_cross_reference` regeneration also expects Related/Refines links to resolve to existing files, so dangling or altered links fail `adr-conformance.md` CI.
