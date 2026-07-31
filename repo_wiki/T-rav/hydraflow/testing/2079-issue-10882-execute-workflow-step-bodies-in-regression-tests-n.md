---
id: 2079
topic: testing
source_issue: 10882
source_phase: plan
created_at: 2026-07-31T12:09:08.255861+00:00
status: superseded
corroborations: 1
superseded_by: 2198
---

# Execute workflow step bodies in regression tests, not string-match

Regression tests for GitHub Actions steps in `tests/regressions/` must execute the real step body under bash — parse the YAML, expand `${{ }}` expressions, and run with fake `gh`/`git` on `PATH`. Skip-guard if `bash`/`jq` are absent (both present in CI).

- `tests/regressions/test_issue_10882.py` runs the committed `resolve` step body against a fake `gh` that 404s the merge-ref probe, asserting `should_run=false` and `skip_reason=merge-ref-absent`.

**Why:** String-matching tests rot silently when step logic changes; executing the committed body catches regressions like a disabled gate or a removed probe.
