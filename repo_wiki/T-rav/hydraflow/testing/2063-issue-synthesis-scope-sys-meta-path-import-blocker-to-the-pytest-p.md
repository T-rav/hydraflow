---
id: 2063
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:50:54.231070+00:00
status: superseded
corroborations: 1
supersedes: 1938
superseded_by: 2192
---

# Scope sys.meta_path import blocker to the pytest process

When adding a `sys.meta_path` blocker for `src.*` imports in `tests/conftest.py`, scope it to the pytest process only. Place it right after the `sys.path` inserts (lines 162–163).

Example: `scripts/hydraflow_audit/__init__.py` and `scripts/sandbox_scenario.py` both insert their own path and must keep importing `src.*` without the blocker firing. Verify the sandbox lane stays green after adding the blocker.

**Why:** An unscoped blocker breaks real consumers that legitimately use `src.`-prefixed imports outside tests.
