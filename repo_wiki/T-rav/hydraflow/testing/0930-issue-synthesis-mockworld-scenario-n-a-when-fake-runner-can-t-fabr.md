---
id: 0930
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T01:16:19.595669+00:00
status: active
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
---

# MockWorld scenario N/A when fake runner can't fabricate the trigger

For #10393, the fake subprocess runner sets `.pid=None`, so a MockWorld scenario can never construct a fake with a sensitive pid (`1`/`os.getpid()`/`os.getppid()`) — the condition that triggers the bug.

Example: per `docs/standards/testing/README.md`'s three-layer pyramid, when a MockWorld layer genuinely cannot exercise the failure mode, the regression test's real-path exercise (real `terminate_processes` + real `os.killpg` spy) substitutes as the loop-integration coverage instead.

**Why:** documents when skipping a pyramid layer is a legitimate architectural constraint rather than the procedural failure the standard normally flags.
