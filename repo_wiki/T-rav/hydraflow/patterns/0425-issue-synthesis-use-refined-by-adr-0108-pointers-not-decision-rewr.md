---
id: 0425
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:37:01.325640+00:00
status: superseded
corroborations: 1
supersedes: 0402,0403,0404,0405,0406,0407,0408,0409,0410,0411,0412,0413,0414,0415
superseded_by: 0432
---

# Use 'Refined by ADR-0108' pointers, not decision rewrites, for extended ADRs

When a new ADR extends an already-Accepted ADR's contract, add a one-line "Refined by ADR-NNNN" pointer to the older ADR instead of rewriting its decision text — mirror the existing ADR-0094↔ADR-0102 convention. Example: ADR-0108 refines ADR-0059/0095/0102 by adding a self-modification fail-closed STOP/HITL disposition; each gets an additive pointer line, so the diff is insertion-only. **Why:** rewriting shipped decision text can misstate flag defaults or contradict deployed behavior; `adr_cross_reference` regeneration also expects Related/Refines links to resolve to existing files, so dangling or altered links fail `adr-conformance.md` CI.
