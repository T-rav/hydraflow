---
id: 0705
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.883037+00:00
status: superseded
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
superseded_by: 0712
---

# MockWorld scenario N/A when fake runner can't fabricate the trigger

For #10393, the fake subprocess runner sets `.pid=None`, so a MockWorld scenario can never construct a fake with a sensitive pid (`1`/`os.getpid()`/`os.getppid()`) — the condition that triggers the bug.

Example: per `docs/standards/testing/README.md`'s three-layer pyramid, when a MockWorld layer genuinely cannot exercise the failure mode, the regression test's real-path exercise (real `terminate_processes` + real `os.killpg` spy) substitutes as the loop-integration coverage instead.

**Why:** documents when skipping a pyramid layer is a legitimate architectural constraint rather than the procedural failure the standard normally flags.
