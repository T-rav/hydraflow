---
id: 0011
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.827860+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
superseded_by: 0034
---

# Use Python script stand-ins to test subprocess boundaries

Create small Python scripts that log invocations to JSON-lines files instead of mocking subprocess calls directly.

Example: Pass `subprocess_runner = ["python3", "fake_gh.py"]` to the system under test; assert via `json.loads(log_path.read_text())`.

**Why:** Real subprocess boundaries catch shell-quoting, PATH resolution, and argument-passing bugs that mock-based patches cannot detect.
