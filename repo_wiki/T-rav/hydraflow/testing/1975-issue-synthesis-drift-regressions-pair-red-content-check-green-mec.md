---
id: 1975
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:50:53.051652+00:00
status: active
corroborations: 1
supersedes: 1848
---

# Drift regressions pair red content-check + green mechanism-check

Ship two tests: one red until the ADR text is fixed (asserts the ADR body contains a token from a set), the other green throughout (proves the drift-detection mechanism itself still fires correctly).

Example: tests/regressions/test_issue_10304.py — only the content-check test should flip during the fix.

**Why:** If both tests were red-then-green, you couldn't tell whether a passing suite meant the ADR was fixed or the detector was broken.
