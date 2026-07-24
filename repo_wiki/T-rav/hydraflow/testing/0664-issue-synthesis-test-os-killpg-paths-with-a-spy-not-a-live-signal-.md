---
id: 0664
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:31:08.510171+00:00
status: active
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631
---

# Test os.killpg paths with a spy, not a live signal, for CI safety

`tests/regressions/test_issue_10393.py` patches `os.killpg` as a spy and exercises the real `kill_process_group` / `runner_utils.terminate_processes` paths with fakes carrying sensitive `.pid` values (`1`, `os.getpid()`, `os.getppid()`). Assert the spy is never called for those pids and that the fallback `proc.kill()` fires instead — this proves the platform-divergent Linux-SIGKILL/macOS-EPERM bug is fixed without ever emitting a live signal, so the test is safe on any host including the CI runner itself.

**Why:** issuing a real `os.killpg` inside a test that runs under pytest risks killing the very process group running the test suite — the exact bug being regression-tested.
