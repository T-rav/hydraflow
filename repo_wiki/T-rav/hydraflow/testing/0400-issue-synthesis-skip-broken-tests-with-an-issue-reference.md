---
id: 0400
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:49:52.745072+00:00
status: active
corroborations: 1
supersedes: 0334,0335,0336,0337,0338,0339,0340,0341,0342,0343,0344,0345,0346,0347,0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369,0370,0371,0372
---

# Skip broken tests with an issue reference

Mark broken tests with a referenced issue, never a bare skip. Remove the skip immediately after the issue is resolved.

Example: `@pytest.mark.skip(reason="documenting bug: #1234")`

**Why:** Without an issue reference, skipped tests become permanent dead weight with no path to removal or triage.
