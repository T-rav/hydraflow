---
id: 1294
topic: gotchas
source_issue: 11124
source_phase: plan
created_at: 2026-08-14T11:33:53.102453+00:00
status: active
corroborations: 1
---

# Zero tags in source makes merge per-matcher loop dead code

When `.claude/settings.json` has zero `_hydraflow` tags, `src_by_matcher` in `merge_settings_file` is always empty, making the per-matcher merge loop (~`scripts/merge_assets.py:216`) dead code. Adding tags activates this never-run path.

The loop reads `e["matcher"]` unguarded; a target whose Stop entry omits the optional `matcher` key (legal in Claude Code) raises `KeyError`. Fix: `e.get("matcher")`.

**Why:** Code paths that have never executed in production harbor latent crashes invisible until a data fix turns them on.
