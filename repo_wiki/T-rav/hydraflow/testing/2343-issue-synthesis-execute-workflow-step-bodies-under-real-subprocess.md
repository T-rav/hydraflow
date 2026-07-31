---
id: 2343
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:37.084169+00:00
status: active
corroborations: 1
supersedes: 2198
---

# Execute workflow step bodies under real subprocess in regressions

Regression tests for GitHub Actions steps must execute the real `run:` body — parse the YAML, expand `${{ }}` expressions, and run under real `subprocess` with fake `gh`/`git` on `PATH`. No `unittest.mock` of shell execution, no string-matching.

Example: `tests/regressions/test_issue_10881.py` replays the `resolve` step of `rc-promotion-scenario.yml` against CONFLICTING/CLEAN PR fixtures.

**Why:** Mocking the shell hides quoting, env-var expansion, and `set -e` semantics; string-matching tests rot silently when step logic changes.
