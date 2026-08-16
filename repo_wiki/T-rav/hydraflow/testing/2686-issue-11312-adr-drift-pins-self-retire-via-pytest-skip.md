---
id: 2686
topic: testing
source_issue: 11312
source_phase: plan
created_at: 2026-08-16T07:21:09.104033+00:00
status: active
corroborations: 1
---

# ADR-drift pins self-retire via pytest.skip

Regression tests for ADR conformance must self-retire: `pytest.skip` when the ADR stops being live or drops its `pytest:` checks. Drive checks through a real `ADRIndex` parse, not a hand-copied node list.

- Include a liveness guard asserting at least one check reports PASS (not SKIPPED) so the test cannot go vacuously green.
- Example: `tests/regressions/test_issue_11312.py` skips if ADR-0134 is no longer live.

**Why:** Hard-coded ADR expectations block CI when ADRs evolve; self-retiring pins keep the regression surface maintainable.
