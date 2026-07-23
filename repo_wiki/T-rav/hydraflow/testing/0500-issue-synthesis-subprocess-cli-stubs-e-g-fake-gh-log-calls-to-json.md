---
id: 0500
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T09:43:13.303873+00:00
status: superseded
corroborations: 1
supersedes: 0492,0493,0494,0495,0496,0497,0498,0499
superseded_by: 0510
---

# Subprocess CLI stubs (e.g. fake gh) log calls to JSONL

Replace real CLI dependencies (e.g. `gh`) in tests with a small script that accepts the same arguments, writes each invocation to a JSONL file, and exits 0.

Example: `subprocess_runner = ['python3', 'fake_gh.py']`; assert behavior by parsing the log: `json.loads(log_path.read_text())`. See also: testing — Concurrent JSONL appends: assert exact line counts.

**Why:** Real subprocess boundaries catch shell-quoting, PATH resolution, and argument-passing bugs that mock-based patches cannot detect.
