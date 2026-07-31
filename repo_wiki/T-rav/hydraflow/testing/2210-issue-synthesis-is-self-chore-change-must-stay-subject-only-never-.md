---
id: 2210
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T14:26:19.477273+00:00
status: superseded
corroborations: 1
supersedes: 2083
superseded_by: 2354
---

# is_self_chore_change must stay subject-only, never read changed_paths

`is_self_chore_change` in `src/audit/sampling.py` inspects only the commit subject. The gauntlet bypass lives in `select_sample`, not in the predicate.

Example: `test_predicate_remains_subject_only` enforces this; grep for `changed_paths` in the predicate body returns nothing.

**Why:** Coupling a subject predicate to path data merges two orthogonal classification axes, breaking the invariant that exclusion is subject-driven and blast-radius is path-driven.
