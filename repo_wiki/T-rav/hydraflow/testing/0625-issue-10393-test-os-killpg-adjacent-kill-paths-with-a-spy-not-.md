---
id: 0625
topic: testing
source_issue: 10393
source_phase: plan
created_at: 2026-07-24T04:45:18.082080+00:00
status: active
corroborations: 1
---

# Test os.killpg-adjacent kill paths with a spy, not a live signal, for host-agnostic CI

`tests/regressions/test_issue_10393.py` patches `os.killpg` as a spy and exercises the real `kill_process_group` / `runner_utils.terminate_processes` paths with fakes carrying sensitive `.pid` values (`1`, `os.getpid()`, `os.getppid()`). Assert the spy is never called for those pids and that the fallback `proc.kill()` fires instead — this proves the platform-divergent Linux-SIGKILL/macOS-EPERM bug is fixed without ever emitting a live signal, so the test is safe on any host including the CI runner itself.

**Why:** issuing a real `os.killpg` inside a test that runs under pytest risks killing the very process group running the test suite — the exact bug being regression-tested.
