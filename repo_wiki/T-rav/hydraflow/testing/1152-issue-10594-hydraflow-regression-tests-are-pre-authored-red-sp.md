---
id: 1152
topic: testing
source_issue: 10594
source_phase: plan
created_at: 2026-07-26T04:15:06.679703+00:00
status: superseded
corroborations: 1
superseded_by: 1154
---

# hydraflow regression tests are pre-authored RED specs, not post-hoc coverage

For issue-driven fixes, `tests/regressions/test_issue_<N>.py` (e.g. `test_issue_10594.py`) can already exist in the working tree before implementation starts, written RED against the current bug. Treat it as the authored spec — don't rewrite it, just make it pass, and add any cases it doesn't pin (e.g. tuple-unpack, function-local negatives) to the adjacent unit test file (`tests/test_wiki_rot_citations.py`) instead.

**Why:** rewriting the regression spec to fit the implementation defeats its purpose as an independent acceptance check.
