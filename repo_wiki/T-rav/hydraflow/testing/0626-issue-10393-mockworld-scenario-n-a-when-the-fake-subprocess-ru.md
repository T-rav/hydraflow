---
id: 0626
topic: testing
source_issue: 10393
source_phase: plan
created_at: 2026-07-24T04:45:18.082087+00:00
status: superseded
corroborations: 1
superseded_by: 0632
---

# MockWorld scenario N/A when the fake subprocess runner can't fabricate the trigger condition

For #10393, the fake subprocess runner sets `.pid=None`, so a MockWorld scenario can never construct a fake with a sensitive pid (`1`/`os.getpid()`/`os.getppid()`) — the condition that triggers the bug. Per `docs/standards/testing/README.md`'s three-layer pyramid, when a MockWorld layer genuinely cannot exercise the failure mode, the regression test's real-path exercise (P1 in this plan: real `terminate_processes` + real `os.killpg` spy) substitutes as the loop-integration coverage instead.

**Why:** documents when skipping a pyramid layer is a legitimate architectural constraint rather than the procedural failure the standard normally flags.
