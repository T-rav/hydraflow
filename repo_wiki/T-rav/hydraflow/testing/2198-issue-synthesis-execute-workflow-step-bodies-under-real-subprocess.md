---
id: 2198
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T14:26:19.446549+00:00
status: superseded
corroborations: 1
supersedes: 2069,2079
superseded_by: 2343
---

# Execute workflow step bodies under real subprocess in regressions

Regression tests for GitHub Actions steps must execute the real `run:` body — parse the YAML, expand `${{ }}` expressions, and run under real `subprocess` with fake `gh`/`git` on `PATH`. No `unittest.mock` of shell execution, no string-matching.

Example: tests/regressions/test_issue_10881.py replays the `resolve` step of `rc-promotion-scenario.yml` against CONFLICTING/CLEAN PR fixtures; tests/regressions/test_issue_10882.py runs the committed `resolve` step body against a fake `gh` that 404s the merge-ref probe.

**Why:** Mocking the shell hides quoting, env-var expansion, and `set -e` semantics; string-matching tests rot silently when step logic changes.
