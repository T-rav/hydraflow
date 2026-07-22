---
id: 0543
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T17:03:32.118939+00:00
status: active
corroborations: 1
supersedes: 0531,0532,0533,0534,0535,0536,0537,0538,0539,0540,0541
---

# Subprocess CLI stubs (e.g. fake_gh) log calls to JSONL

Replace real CLI dependencies (e.g. `gh`) in tests with a small script that accepts the same arguments, writes each invocation to a JSONL file, and exits 0.

Example: `subprocess_runner = ['python3', 'fake_gh.py']`, used across `tests/test_auto_pr.py` and scenario tests; assert behavior by parsing the log: `json.loads(log_path.read_text())`. See also: testing — Concurrent JSONL appends: assert exact line counts.

**Why:** Real subprocess boundaries catch shell-quoting, PATH resolution, and argument-passing bugs that mock-based patches cannot detect.
