---
id: 2116
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T14:26:19.242134+00:00
status: superseded
corroborations: 1
supersedes: 1986
superseded_by: 2261
---

# Test os.killpg paths with a spy, not a live signal

Patch os.killpg as a spy and exercise real kill_process_group / runner_utils.terminate_processes paths with fakes carrying sensitive .pid values (1, os.getpid(), os.getppid()).

Example: tests/regressions/test_issue_10393.py asserts the spy is never called for those pids and that the fallback proc.kill() fires instead.

**Why:** Issuing a real os.killpg inside a test risks killing the very process group running the test suite.
