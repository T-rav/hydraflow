---
id: 0157
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T06:37:30.575641+00:00
status: active
corroborations: 1
supersedes: 0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152
---

# Use Python script stand-ins to test subprocess boundaries

Create small Python scripts that log invocations to JSON-lines files instead of mocking subprocess calls directly.

Example: Pass `subprocess_runner = ['python3', 'fake_gh.py']` to the system under test; assert via `json.loads(log_path.read_text())`.

**Why:** Real subprocess boundaries catch shell-quoting, PATH resolution, and argument-passing bugs that mock-based patches cannot detect.
