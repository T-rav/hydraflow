---
id: 1259
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T20:11:03.189336+00:00
status: superseded
corroborations: 1
supersedes: 1185
superseded_by: 1333
---

# MockWorld scenario N/A when fake can't fabricate trigger

When a MockWorld layer genuinely cannot exercise the failure mode, the regression test's real-path exercise substitutes as loop-integration coverage per docs/standards/testing/README.md's three-layer pyramid.

Example: for #10393, the fake subprocess runner sets .pid=None, so a MockWorld scenario can never construct a fake with a sensitive pid (1/os.getpid()/os.getppid()).

**Why:** Documents when skipping a pyramid layer is a legitimate architectural constraint rather than the procedural failure the standard normally flags.
