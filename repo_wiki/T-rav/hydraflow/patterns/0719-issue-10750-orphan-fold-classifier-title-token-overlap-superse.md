---
id: 0719
topic: patterns
source_issue: 10750
source_phase: plan
created_at: 2026-07-27T22:53:53.519973+00:00
status: superseded
corroborations: 1
superseded_by: 0775
---

# Orphan-fold classifier: title-token overlap + supersedes count ≥2

`plan_orphan_restores` in `src/wiki_supersession_repair.py` classifies a `left_on_primary` predecessor as `orphan_fold` when its target's `supersedes` has ≥2 ids AND the two normalized H1 titles share no content-token overlap. Genuine N-to-1 merges (overlapping titles) stay `left_on_primary`. **Why:** Mis-classifying a genuine merge re-activates duplicate content; dry-run default and `--only-id` scoping mitigate residual risk.
