---
id: 1806
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T04:20:59.148976+00:00
status: active
corroborations: 1
supersedes: 1712
---

# Pin no-intake for analysis tools with zero-mutating-call tests

Enforce no-intake for read-only analysis tools with a test asserting zero mutating `FakeGitHub` calls, not by convention.

Example: `tests/test_interaction_report.py` asserts a full run makes zero mutating `FakeGitHub` calls.

**Why:** A study that files issues or opens PRs feeds what it measures, corrupting its own interaction data and creating feedback loops in the ranking.
