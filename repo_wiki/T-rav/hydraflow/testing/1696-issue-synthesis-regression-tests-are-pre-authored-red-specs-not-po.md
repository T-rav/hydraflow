---
id: 1696
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T02:43:14.345723+00:00
status: active
corroborations: 1
supersedes: 1613
---

# Regression tests are pre-authored RED specs, not post-hoc

For issue-driven fixes, tests/regressions/test_issue_<N>.py can already exist in the working tree before implementation starts, written RED against the current bug. Treat it as the authored spec — don't rewrite it, just make it pass, and add any cases it doesn't pin to the adjacent unit test file instead.

Example: tuple-unpack, function-local negatives go to tests/test_wiki_rot_citations.py, not the regression spec.

**Why:** Rewriting the regression spec to fit the implementation defeats its purpose as an independent acceptance check.
