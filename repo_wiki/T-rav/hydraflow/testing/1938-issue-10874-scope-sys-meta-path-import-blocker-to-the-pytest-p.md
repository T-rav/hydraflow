---
id: 1938
topic: testing
source_issue: 10874
source_phase: plan
created_at: 2026-07-31T06:49:10.357906+00:00
status: active
corroborations: 1
---

# Scope sys.meta_path import blocker to the pytest process

When adding a `sys.meta_path` blocker for `src.*` imports in `tests/conftest.py`, scope it to the pytest process only. Place it right after the `sys.path` inserts (lines 162–163).

- `scripts/hydraflow_audit/__init__.py` inserts its own path
- `scripts/sandbox_scenario.py` inserts its own path
- Both must keep importing `src.*` without the blocker firing

Verify the sandbox lane stays green after adding the blocker.

**Why:** An unscoped blocker breaks real consumers that legitimately use `src.`-prefixed imports outside tests.
