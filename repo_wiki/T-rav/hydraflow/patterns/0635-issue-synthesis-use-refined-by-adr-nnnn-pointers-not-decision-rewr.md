---
id: 0635
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T20:03:14.307839+00:00
status: superseded
corroborations: 1
supersedes: 0593
superseded_by: 0680
---

# Use 'Refined by ADR-NNNN' pointers, not decision rewrites

When a new ADR extends an already-Accepted ADR's contract, add a one-line "Refined by ADR-NNNN" pointer to the older ADR instead of rewriting its decision text.

Example: ADR-0108 refines ADR-0059/0095/0102 by adding a self-modification fail-closed STOP/HITL disposition; each gets an additive pointer line, so the diff is insertion-only.

**Why:** Rewriting shipped decision text can misstate flag defaults or contradict deployed behavior; `adr_cross_reference` regeneration expects Related/Refines links to resolve to existing files.
