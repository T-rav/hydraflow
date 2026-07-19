---
id: 0416
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:46:15.847031+00:00
status: active
corroborations: 1
supersedes: 0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387,0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401,0402,0403,0404,0405,0406,0407,0408,0409,0410,0411
---

# Use tmp_path with ConfigFactory for file-based test I/O

All tests that read or write files must use pytest's `tmp_path` combined with `ConfigFactory.create(base_path=tmp_path)`, never writing to real project paths.

Example: `def test_something(tmp_path): config = ConfigFactory.create(base_path=tmp_path)`

**Why:** Writing to project paths pollutes the working tree and causes cross-test interference, especially under parallel execution.
