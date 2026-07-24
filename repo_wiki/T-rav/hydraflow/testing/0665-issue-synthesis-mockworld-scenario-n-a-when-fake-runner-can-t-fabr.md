---
id: 0665
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:31:08.511193+00:00
status: superseded
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631
superseded_by: 0672
---

# MockWorld scenario N/A when fake runner can't fabricate the trigger

For #10393, the fake subprocess runner sets `.pid=None`, so a MockWorld scenario can never construct a fake with a sensitive pid (`1`/`os.getpid()`/`os.getppid()`) — the condition that triggers the bug. Per `docs/standards/testing/README.md`'s three-layer pyramid, when a MockWorld layer genuinely cannot exercise the failure mode, the regression test's real-path exercise (real `terminate_processes` + real `os.killpg` spy) substitutes as the loop-integration coverage instead.

**Why:** documents when skipping a pyramid layer is a legitimate architectural constraint rather than the procedural failure the standard normally flags.
