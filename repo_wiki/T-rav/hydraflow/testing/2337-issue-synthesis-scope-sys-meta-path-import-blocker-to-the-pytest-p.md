---
id: 2337
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:37.067942+00:00
status: superseded
corroborations: 1
supersedes: 2192
superseded_by: 2526
---

# Scope sys.meta_path import blocker to the pytest process

When adding a `sys.meta_path` blocker for `src.*` imports in `tests/conftest.py`, scope it to the pytest process only. Place it right after the `sys.path` inserts (lines 162–163).

Example: `scripts/hydraflow_audit/__init__.py` and `scripts/sandbox_scenario.py` both insert their own path and must keep importing `src.*` without the blocker firing.

**Why:** An unscoped blocker breaks real consumers that legitimately use `src.`-prefixed imports outside tests.
