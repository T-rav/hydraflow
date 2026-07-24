---
id: 0704
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.881387+00:00
status: superseded
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
superseded_by: 0712
---

# Test os.killpg paths with a spy, not a live signal, for CI safety

`tests/regressions/test_issue_10393.py` patches `os.killpg` as a spy and exercises the real `kill_process_group` / `runner_utils.terminate_processes` paths with fakes carrying sensitive `.pid` values (`1`, `os.getpid()`, `os.getppid()`).

Example: assert the spy is never called for those pids and that the fallback `proc.kill()` fires instead, proving the platform-divergent Linux-SIGKILL/macOS-EPERM bug is fixed without ever emitting a live signal.

**Why:** issuing a real `os.killpg` inside a test that runs under pytest risks killing the very process group running the test suite — the exact bug being regression-tested.
