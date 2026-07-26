---
id: 1016
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.424253+00:00
status: active
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
---

# Subprocess CLI stubs (e.g. fake_gh) log calls to JSONL

Replace real CLI dependencies (e.g. gh) in tests with a small script that accepts the same arguments, writes each invocation to a JSONL file, and exits 0.

Example: subprocess_runner = ['python3', 'fake_gh.py'], used across tests/test_auto_pr.py and scenario tests; assert behavior by parsing the log: json.loads(log_path.read_text()).

**Why:** Real subprocess boundaries catch shell-quoting, PATH resolution, and argument-passing bugs that mock-based patches cannot detect.
