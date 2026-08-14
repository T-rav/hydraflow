---
id: 2439
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:49.549760+00:00
status: active
corroborations: 1
supersedes: 2249
---

# ADR drift fixes: amend stale claim, not cited PR's decision

Repairing ADR drift means correcting the specific stale sentence plus a one-line cross-reference to the source PR/issue, not re-describing or absorbing the other PR's whole decision into this ADR.

Example: #10290's park-behavior decision has its own ADR/regression coverage; ADR-0107 is about collapsing Discover/Shape and should stay scoped to that.

**Why:** Scope creep during drift repair turns a docs-reconciliation PR into an undocumented re-litigation of a decision owned elsewhere.
