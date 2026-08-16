---
id: 3610
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T12:13:23.373077+00:00
status: active
corroborations: 1
supersedes: 3463
---

# Revoke old manifest before re-merge to prevent grant stacking

`merge_assets` in `scripts/merge_assets.py` must call `_revoke_permissions` with the previously loaded manifest before re-merging, then record the fresh install. This mirrors the existing "delete previously installed files" step used for asset files.

**Why:** Without the pre-merge revoke, grants retired from the source remain in the target indefinitely, stacking across repeated onboards and silently widening the permission surface.
