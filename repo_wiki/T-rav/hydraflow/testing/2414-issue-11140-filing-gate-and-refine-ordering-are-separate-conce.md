---
id: 2414
topic: testing
source_issue: 11140
source_phase: plan
created_at: 2026-08-14T14:36:07.424574+00:00
status: active
corroborations: 1
---

# Filing gate and refine ordering are separate concerns

The inefficiency-issue filing gate introduced in #11133 and the refine ordering logic in `pick_refine_order` are deliberately decoupled. Changes to ordering (issue #11140) must not alter which issues get filed or skipped.

When modifying `src/prompt_efficiency.py`, verify `tests/test_skill_prompt_eval_loop.py` still passes the filing gate assertions unchanged.

**Why:** Mixing the two concerns risks silently changing the set of filed issues when only the priority queue was meant to move.
