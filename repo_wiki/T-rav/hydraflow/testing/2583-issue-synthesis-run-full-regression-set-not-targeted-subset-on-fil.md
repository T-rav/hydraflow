---
id: 2583
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.826820+00:00
status: active
corroborations: 1
supersedes: 2397
---

# Run full regression set, not targeted subset, on filing-body changes

When modifying the `_file_inefficiency_issue` body shape in `src/skill_prompt_eval_loop.py`, run the entire `tests/regressions/test_issue_1109*.py` and `1111*.py` set, not a targeted subset. Untracked in-tree regression tests may assert on the same body, and a narrow run will miss in-flight pins.

Example: if a colliding test does not go green via the body-side fix shape it accepts, say so rather than editing its assertions.

**Why:** PR #8460 lesson — targeted regression runs silently passed while colliding in-tree pins broke later.
