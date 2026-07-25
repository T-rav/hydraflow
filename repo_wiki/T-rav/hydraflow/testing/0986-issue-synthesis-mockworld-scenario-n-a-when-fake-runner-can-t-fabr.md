---
id: 0986
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T06:21:18.124098+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0951,0952
---

# MockWorld scenario N/A when fake runner can't fabricate the trigger

For #10393, the fake subprocess runner sets `.pid=None`, so a MockWorld scenario can never construct a fake with a sensitive pid (`1`/`os.getpid()`/`os.getppid()`) — the condition that triggers the bug.

Example: per `docs/standards/testing/README.md`'s three-layer pyramid, when a MockWorld layer genuinely cannot exercise the failure mode, the regression test's real-path exercise (real `terminate_processes` + real `os.killpg` spy) substitutes as the loop-integration coverage instead.

**Why:** documents when skipping a pyramid layer is a legitimate architectural constraint rather than the procedural failure the standard normally flags.
