---
id: 1184
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T18:41:12.874789+00:00
status: superseded
corroborations: 1
supersedes: 1115
superseded_by: 1258
---

# Test os.killpg paths with a spy, not a live signal

Patch os.killpg as a spy and exercise real kill_process_group / runner_utils.terminate_processes paths with fakes carrying sensitive .pid values (1, os.getpid(), os.getppid()).

Example: tests/regressions/test_issue_10393.py asserts the spy is never called for those pids and that the fallback proc.kill() fires instead.

**Why:** Issuing a real os.killpg inside a test that runs under pytest risks killing the very process group running the test suite — the exact bug being regression-tested.
