---
id: 1220
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T18:41:12.933344+00:00
status: active
corroborations: 1
supersedes: 1152
---

# Regression tests are pre-authored RED specs, not post-hoc

For issue-driven fixes, `tests/regressions/test_issue_<N>.py` (e.g. test_issue_10594.py) can already exist in the working tree before implementation starts, written RED against the current bug. Treat it as the authored spec — don't rewrite it, just make it pass, and add any cases it doesn't pin (e.g. tuple-unpack, function-local negatives) to the adjacent unit test file (tests/test_wiki_rot_citations.py) instead.

**Why:** rewriting the regression spec to fit the implementation defeats its purpose as an independent acceptance check.
