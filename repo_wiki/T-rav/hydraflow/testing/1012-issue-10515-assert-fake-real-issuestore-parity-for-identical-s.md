---
id: 1012
topic: testing
source_issue: 10515
source_phase: plan
created_at: 2026-07-25T05:40:37.556706+00:00
status: active
corroborations: 1
---

# Assert Fake/real IssueStore parity for identical seeded state

When fixing status/vocabulary drift in `FakeIssueStore`, add a test that seeds both the Fake and the real `IssueStore` with identical HITL + merged state and asserts their `get_pipeline_snapshot()` terminal-bucket statuses are equal, not just that the Fake matches a hardcoded expectation. See the P1 task graph for issue #10515 (`tests/regressions/test_issue_10515.py`).

**Why:** A Fake-only assertion can pass while re-encoding the same drift the fix was meant to remove; only a side-by-side comparison against the real store proves parity.
