---
id: 0691
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.860247+00:00
status: superseded
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
superseded_by: 0712
---

# ADR drift fixes: amend the stale claim, not the cited PR's whole decision

Repairing ADR drift (e.g. ADR-0107's Routing section vs. #10290's triage-park split) means correcting the specific stale sentence plus a one-line cross-reference to the source PR/issue — not re-describing or absorbing the other PR's whole decision into this ADR.

Example: #10290's park-behavior decision has its own ADR/regression coverage; ADR-0107 is about collapsing Discover/Shape and should stay scoped to that.

**Why:** scope creep during drift repair turns a docs-reconciliation PR into an undocumented re-litigation of a decision owned elsewhere, and duplicates coverage instead of cross-referencing it.
