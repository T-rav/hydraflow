---
id: 0786
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:12:20.350524+00:00
status: superseded
corroborations: 1
supersedes: 0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753
superseded_by: 0798
---

# Test os.killpg paths with a spy, not a live signal, for CI safety

`tests/regressions/test_issue_10393.py` patches `os.killpg` as a spy and exercises the real `kill_process_group` / `runner_utils.terminate_processes` paths with fakes carrying sensitive `.pid` values (`1`, `os.getpid()`, `os.getppid()`).

Example: assert the spy is never called for those pids and that the fallback `proc.kill()` fires instead, proving the platform-divergent Linux-SIGKILL/macOS-EPERM bug is fixed without ever emitting a live signal.

**Why:** issuing a real `os.killpg` inside a test that runs under pytest risks killing the very process group running the test suite — the exact bug being regression-tested.
