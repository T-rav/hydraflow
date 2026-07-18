---
id: 0190
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.785304+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Use Python script stand-ins to test subprocess boundaries

Create small Python scripts that log invocations to JSON-lines files instead of mocking subprocess calls directly.

Example: Pass `subprocess_runner = ['python3', 'fake_gh.py']` to the system under test; assert via `json.loads(log_path.read_text())`.

**Why:** Real subprocess boundaries catch shell-quoting, PATH resolution, and argument-passing bugs that mock-based patches cannot detect.
