---
id: 2354
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:37.114142+00:00
status: active
corroborations: 1
supersedes: 2210
---

# is_self_chore_change must stay subject-only, never read changed_paths

`is_self_chore_change` in `src/audit/sampling.py` inspects only the commit subject. The gauntlet bypass lives in `select_sample`, not in the predicate.

Example: `test_predicate_remains_subject_only` enforces this; grep for `changed_paths` in the predicate body returns nothing.

**Why:** Coupling a subject predicate to path data merges two orthogonal classification axes, breaking the invariant that exclusion is subject-driven and blast-radius is path-driven.
