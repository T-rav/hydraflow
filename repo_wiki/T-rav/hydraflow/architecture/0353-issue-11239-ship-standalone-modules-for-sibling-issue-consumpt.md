---
id: 0353
topic: architecture
source_issue: 11239
source_phase: plan
created_at: 2026-08-15T09:47:55.217032+00:00
status: active
corroborations: 1
---

# Ship standalone modules for sibling-issue consumption, not stubs

When a sibling issue owns a file surface, ship standalone modules it will consume rather than stubbing those files. #11239 ships `RailsFixAction.jsx` + `model/railsFix.js` as standalone view-model + presentational component; #11210's `RepoHealthPanel.jsx` drops them in. Do not create `_health_routes.py` or `scripts/hydraflow_healthcheck/` here. **Why:** Even a minimal stub of a sibling-owned file creates a merge conflict when that issue lands.
