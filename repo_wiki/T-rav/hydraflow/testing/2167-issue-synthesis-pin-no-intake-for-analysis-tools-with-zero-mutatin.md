---
id: 2167
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T14:26:19.368348+00:00
status: superseded
corroborations: 1
supersedes: 2038
superseded_by: 2312
---

# Pin no-intake for analysis tools with zero-mutating-call tests

Enforce no-intake for read-only analysis tools with a test asserting zero mutating `FakeGitHub` calls, not by convention.

Example: `tests/test_interaction_report.py` asserts a full run makes zero mutating `FakeGitHub` calls.

**Why:** A study that files issues or opens PRs feeds what it measures, corrupting its own interaction data and creating feedback loops in the ranking.
