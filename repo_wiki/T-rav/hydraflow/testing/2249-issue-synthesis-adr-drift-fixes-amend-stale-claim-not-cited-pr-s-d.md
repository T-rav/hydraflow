---
id: 2249
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:36.834097+00:00
status: superseded
corroborations: 1
supersedes: 2104
superseded_by: 2439
---

# ADR drift fixes: amend stale claim, not cited PR's decision

Repairing ADR drift means correcting the specific stale sentence plus a one-line cross-reference to the source PR/issue, not re-describing or absorbing the other PR's whole decision into this ADR.

Example: #10290's park-behavior decision has its own ADR/regression coverage; ADR-0107 is about collapsing Discover/Shape and should stay scoped to that.

**Why:** Scope creep during drift repair turns a docs-reconciliation PR into an undocumented re-litigation of a decision owned elsewhere.
