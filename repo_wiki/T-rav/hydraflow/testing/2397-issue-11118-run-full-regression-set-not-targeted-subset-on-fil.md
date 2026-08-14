---
id: 2397
topic: testing
source_issue: 11118
source_phase: plan
created_at: 2026-08-14T10:22:06.549556+00:00
status: superseded
corroborations: 1
superseded_by: 2583
---

# Run full regression set, not targeted subset, on filing-body changes

When modifying the `_file_inefficiency_issue` body shape in `src/skill_prompt_eval_loop.py`, run the entire `tests/regressions/test_issue_1109*.py` and `1111*.py` set, not a targeted subset. Untracked in-tree regression tests (e.g. `test_issue_11116.py`) may assert on the same body, and a narrow run will miss in-flight pins. If a colliding test does not go green via the body-side fix shape it accepts, say so rather than editing its assertions.

**Why:** PR #8460 lesson — targeted regression runs silently passed while colliding in-tree pins broke later.
