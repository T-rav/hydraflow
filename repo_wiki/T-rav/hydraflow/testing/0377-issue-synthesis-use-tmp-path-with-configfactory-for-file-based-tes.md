---
id: 0377
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:49:52.721475+00:00
status: superseded
corroborations: 1
supersedes: 0334,0335,0336,0337,0338,0339,0340,0341,0342,0343,0344,0345,0346,0347,0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369,0370,0371,0372
superseded_by: 0412
---

# Use tmp_path with ConfigFactory for file-based test I/O

All tests that read or write files must use pytest's `tmp_path` combined with `ConfigFactory.create(base_path=tmp_path)`, never writing to real project paths.

Example: `def test_something(tmp_path): config = ConfigFactory.create(base_path=tmp_path)`

**Why:** Writing to project paths pollutes the working tree and causes cross-test interference, especially under parallel execution.
