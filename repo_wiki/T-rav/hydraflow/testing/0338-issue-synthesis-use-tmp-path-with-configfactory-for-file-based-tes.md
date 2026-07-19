---
id: 0338
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:25:25.490097+00:00
status: active
corroborations: 1
supersedes: 0295,0296,0297,0298,0299,0300,0301,0302,0303,0304,0305,0306,0307,0308,0309,0310,0311,0312,0313,0314,0315,0316,0317,0318,0319,0320,0321,0322,0323,0324,0325,0326,0327,0328,0329,0330,0331,0332,0333
---

# Use tmp_path with ConfigFactory for file-based test I/O

All tests that read or write files must use pytest's `tmp_path` combined with `ConfigFactory.create(base_path=tmp_path)`, never writing to real project paths.

Example: `def test_something(tmp_path): config = ConfigFactory.create(base_path=tmp_path)`

**Why:** Writing to project paths pollutes the working tree and causes cross-test interference, especially under parallel execution.
