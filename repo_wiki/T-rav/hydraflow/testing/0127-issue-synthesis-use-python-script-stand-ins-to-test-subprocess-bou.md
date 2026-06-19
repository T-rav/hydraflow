---
id: 0127
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T05:57:54.433073+00:00
status: superseded
corroborations: 1
supersedes: 0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122
superseded_by: 0153
---

# Use Python script stand-ins to test subprocess boundaries

Create small Python scripts that log invocations to JSON-lines files instead of mocking subprocess calls directly.

Example: Pass `subprocess_runner = ['python3', 'fake_gh.py']` to the system under test; assert via `json.loads(log_path.read_text())`.

**Why:** Real subprocess boundaries catch shell-quoting, PATH resolution, and argument-passing bugs that mock-based patches cannot detect.
