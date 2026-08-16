---
id: 2691
topic: testing
source_issue: 11316
source_phase: plan
created_at: 2026-08-16T07:49:06.673213+00:00
status: active
corroborations: 1
---

# Run full make quality for subprocess_util changes

Do not run file-targeted test subsets when modifying `src/subprocess_util.py`. Execute the full `make quality` suite.

Example: After modifying `make_clean_env`, run `make quality`, then re-run targeted tests like `tests/test_llm_provider.py` with `ANTHROPIC_BASE_URL` exported in the shell to prove host-leak clusters are green.

**Why:** `subprocess_util.py` is a shared dependency across most test suites; targeted runs miss regressions in unrelated loops or workers.
