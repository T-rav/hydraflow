---
id: 1048
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.507750+00:00
status: active
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
---

# MockWorld scenario N/A when fake runner can't fabricate the trigger

For #10393, the fake subprocess runner sets .pid=None, so a MockWorld scenario can never construct a fake with a sensitive pid (1/os.getpid()/os.getppid()) — the condition that triggers the bug.

Example: per docs/standards/testing/README.md's three-layer pyramid, when a MockWorld layer genuinely cannot exercise the failure mode, the regression test's real-path exercise (real terminate_processes + real os.killpg spy) substitutes as the loop-integration coverage instead.

**Why:** documents when skipping a pyramid layer is a legitimate architectural constraint rather than the procedural failure the standard normally flags.
