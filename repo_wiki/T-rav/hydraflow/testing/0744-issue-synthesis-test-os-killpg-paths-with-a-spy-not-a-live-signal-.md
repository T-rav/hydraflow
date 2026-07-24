---
id: 0744
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:42:21.337774+00:00
status: active
corroborations: 1
supersedes: 0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703,0704,0705,0706,0707,0708,0709,0710,0711
---

# Test os.killpg paths with a spy, not a live signal, for CI safety

`tests/regressions/test_issue_10393.py` patches `os.killpg` as a spy and exercises the real `kill_process_group` / `runner_utils.terminate_processes` paths with fakes carrying sensitive `.pid` values (`1`, `os.getpid()`, `os.getppid()`).

Example: assert the spy is never called for those pids and that the fallback `proc.kill()` fires instead, proving the platform-divergent Linux-SIGKILL/macOS-EPERM bug is fixed without ever emitting a live signal.

**Why:** issuing a real `os.killpg` inside a test that runs under pytest risks killing the very process group running the test suite — the exact bug being regression-tested.
