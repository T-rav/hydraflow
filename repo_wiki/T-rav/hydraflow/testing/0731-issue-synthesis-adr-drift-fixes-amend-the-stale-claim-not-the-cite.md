---
id: 0731
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:42:21.316112+00:00
status: active
corroborations: 1
supersedes: 0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703,0704,0705,0706,0707,0708,0709,0710,0711
---

# ADR drift fixes: amend the stale claim, not the cited PR's whole decision

Repairing ADR drift (e.g. ADR-0107's Routing section vs. #10290's triage-park split) means correcting the specific stale sentence plus a one-line cross-reference to the source PR/issue — not re-describing or absorbing the other PR's whole decision into this ADR.

Example: #10290's park-behavior decision has its own ADR/regression coverage; ADR-0107 is about collapsing Discover/Shape and should stay scoped to that.

**Why:** scope creep during drift repair turns a docs-reconciliation PR into an undocumented re-litigation of a decision owned elsewhere, and duplicates coverage instead of cross-referencing it.
