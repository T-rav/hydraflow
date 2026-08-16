---
id: 2694
topic: testing
source_issue: 11320
source_phase: plan
created_at: 2026-08-16T08:37:33.480345+00:00
status: active
corroborations: 1
---

# PROMPT_BASELINE sets use exact-equality assertion in test_prompt_fitness

When you change prompt fencing in any runner, you must re-pin `PROMPT_BASELINE["<runner>"]` in `src/prompt_fitness.py` (~line 294) to the new per-criterion set. `tests/test_prompt_fitness.py` asserts exact set equality, so a stale pin fails the build immediately.

- Run the test, read the reported expected set, update the dict.
- The test is the gate proving the baseline was re-pinned, not papered over.

**Why:** Without exact-equality, a silently passing baseline masks regressions in XML tag structure or untrusted-region count.
