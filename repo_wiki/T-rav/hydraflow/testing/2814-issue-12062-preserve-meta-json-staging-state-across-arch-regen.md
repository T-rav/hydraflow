---
id: 2814
topic: testing
source_issue: 12062
source_phase: plan
created_at: 2026-09-02T22:21:22.693549+00:00
status: active
corroborations: 1
---

# Preserve .meta.json staging state across arch regen in bot PRs

Snapshot whether `docs/arch/.meta.json` is staged before regen via `git diff --cached --name-only -- docs/arch/.meta.json`. Restore with `git checkout HEAD -- docs/arch/.meta.json` only if not pre-staged. Per #10167, DiagramLoop intentionally stages branch-specific `.meta.json`; restoring when caller didn't stage it un-DIRTYs re-armed merge conflicts.
