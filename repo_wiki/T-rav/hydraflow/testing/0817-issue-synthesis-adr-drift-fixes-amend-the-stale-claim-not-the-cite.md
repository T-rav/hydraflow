---
id: 0817
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:43:21.191679+00:00
status: superseded
corroborations: 1
supersedes: 0754,0755,0756,0757,0758,0759,0760,0761,0762,0763,0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797
superseded_by: 0847
---

# ADR drift fixes: amend the stale claim, not the cited PR's whole decision

Repairing ADR drift (e.g. ADR-0107's Routing section vs. #10290's triage-park split) means correcting the specific stale sentence plus a one-line cross-reference to the source PR/issue — not re-describing or absorbing the other PR's whole decision into this ADR.

Example: #10290's park-behavior decision has its own ADR/regression coverage; ADR-0107 is about collapsing Discover/Shape and should stay scoped to that.

**Why:** scope creep during drift repair turns a docs-reconciliation PR into an undocumented re-litigation of a decision owned elsewhere, and duplicates coverage instead of cross-referencing it.
