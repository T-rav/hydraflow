---
id: 0299
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:56:41.004385+00:00
status: superseded
corroborations: 1
supersedes: 0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294
superseded_by: 0334
---

# Use tmp_path with ConfigFactory for all file-based test I/O

All tests that read or write files must use pytest's `tmp_path` combined with `ConfigFactory.create(base_path=tmp_path)` — never write to real project paths.

Example: `def test_something(tmp_path): config = ConfigFactory.create(base_path=tmp_path)`

**Why:** Writing to project paths pollutes the working tree and causes cross-test interference, especially under parallel execution.
