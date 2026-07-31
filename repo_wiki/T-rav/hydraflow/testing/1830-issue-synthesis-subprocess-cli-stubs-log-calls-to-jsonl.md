---
id: 1830
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T06:59:05.622377+00:00
status: active
corroborations: 1
supersedes: 1725
---

# Subprocess CLI stubs log calls to JSONL

Replace real CLI dependencies (e.g. gh) in tests with a script that accepts the same arguments, writes each invocation to a JSONL file, and exits 0.

Example: `subprocess_runner = ['python3', 'fake_gh.py']`; assert behavior by parsing `json.loads(log_path.read_text())`.

**Why:** Real subprocess boundaries catch shell-quoting, PATH resolution, and argument-passing bugs that mock patches cannot detect.
