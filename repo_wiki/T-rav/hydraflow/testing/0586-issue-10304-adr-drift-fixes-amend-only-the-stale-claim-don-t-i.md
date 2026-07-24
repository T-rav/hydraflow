---
id: 0586
topic: testing
source_issue: 10304
source_phase: plan
created_at: 2026-07-24T03:55:27.919587+00:00
status: active
corroborations: 1
---

# ADR drift fixes: amend only the stale claim, don't import the cited PR's full decision

Repairing ADR drift (e.g. ADR-0107's Routing section vs. #10290's triage-park split) means correcting the specific stale sentence plus a one-line cross-reference to the source PR/issue — not re-describing or absorbing the other PR's whole decision into this ADR. #10290's park-behavior decision has its own ADR/regression coverage; ADR-0107 is about collapsing Discover/Shape and should stay scoped to that.

**Why:** scope creep during drift repair turns a docs-reconciliation PR into an undocumented re-litigation of a decision owned elsewhere, and duplicates coverage instead of cross-referencing it.
