---
id: 1629
topic: testing
source_issue: 10823
source_phase: plan
created_at: 2026-07-31T00:48:51.333117+00:00
status: superseded
corroborations: 1
superseded_by: 1712
---

# Pin no-intake for analysis tools with zero-mutating-call tests

Enforce no-intake for read-only analysis tools with a test asserting zero mutating `FakeGitHub` calls, not by convention.

`tests/test_interaction_report.py` asserts a full run makes zero mutating `FakeGitHub` calls.

**Why:** A study that files issues or opens PRs feeds what it measures, corrupting its own interaction data and creating feedback loops in the ranking.
