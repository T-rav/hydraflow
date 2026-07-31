---
id: 1860
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T06:59:05.969112+00:00
status: active
corroborations: 1
supersedes: 1755
---

# MockWorld scenario N/A when fake can't fabricate trigger

When a MockWorld layer genuinely cannot exercise the failure mode, the regression test's real-path exercise substitutes as loop-integration coverage per docs/standards/testing/README.md's three-layer pyramid.

Example: for #10393, the fake subprocess runner sets .pid=None, so a MockWorld scenario can never construct a fake with a sensitive pid.

**Why:** Documents when skipping a pyramid layer is a legitimate architectural constraint rather than the procedural failure the standard normally flags.
