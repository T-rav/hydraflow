---
id: 0955
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.541044+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
---

# Subprocess CLI stubs (e.g. fake_gh) log calls to JSONL

Replace real CLI dependencies (e.g. gh) in tests with a small script that accepts the same arguments, writes each invocation to a JSONL file, and exits 0.

Example: subprocess_runner = ['python3', 'fake_gh.py'], used across tests/test_auto_pr.py and scenario tests; assert behavior by parsing the log: json.loads(log_path.read_text()).

**Why:** Real subprocess boundaries catch shell-quoting, PATH resolution, and argument-passing bugs that mock-based patches cannot detect.
