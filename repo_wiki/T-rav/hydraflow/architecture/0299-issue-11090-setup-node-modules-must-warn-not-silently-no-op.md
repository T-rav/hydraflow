---
id: 0299
topic: architecture
source_issue: 11090
source_phase: plan
created_at: 2026-08-14T06:25:31.261903+00:00
status: active
corroborations: 1
---

# _setup_node_modules must warn, not silently no-op

`WorkspaceManager._setup_node_modules` must log a warning (literal format string, no `_`-prefixed cross-module import) naming the UI directory when a detected UI source dir gets no `node_modules`.

Cover with `tests/test_workspace_env.py` + `caplog`: missing host deps → warning; present → provisioned, no warning.

**Why:** Silent no-ops push the failure surface from provisioning time to `make quality` time, where the diagnosis is far less actionable.
