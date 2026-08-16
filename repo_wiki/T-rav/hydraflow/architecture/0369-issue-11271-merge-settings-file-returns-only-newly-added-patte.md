---
id: 0369
topic: architecture
source_issue: 11271
source_phase: plan
created_at: 2026-08-16T05:09:28.497210+00:00
status: active
corroborations: 1
---

# merge_settings_file returns only newly added patterns

`merge_settings_file` in `scripts/merge_assets.py` must return `{"allow": [...], "deny": [...]}` containing only patterns it actually added — patterns already present in the target are no-ops and must not appear. The wholesale-copy path (no target settings) reports all source permissions.

**Why:** The return value feeds the manifest that `--clean` revokes from. Reporting a pre-existing pattern would cause `SHARED_ALLOW` entries to be stripped on offboard, destroying user-authored grants.
