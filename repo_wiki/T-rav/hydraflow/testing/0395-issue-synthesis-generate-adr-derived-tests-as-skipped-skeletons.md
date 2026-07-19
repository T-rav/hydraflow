---
id: 0395
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:49:52.739830+00:00
status: active
corroborations: 1
supersedes: 0334,0335,0336,0337,0338,0339,0340,0341,0342,0343,0344,0345,0346,0347,0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369,0370,0371,0372
---

# Generate ADR-derived tests as skipped skeletons

Extract baseline invariants (uniqueness, usage, negative, coverage) from an ADR's Decision section and generate each test as a skipped skeleton.

Example: `@pytest.mark.skip(reason='skeleton: requires human review')`

**Why:** Auto-generating non-skipped tests from ambiguous ADR language creates brittle tests that break on legitimate wording updates.
