---
id: 1375
topic: gotchas
source_issue: 11211
source_phase: review
created_at: 2026-08-15T06:58:01.011518+00:00
status: active
corroborations: 1
---

# Dashboard badges must reflect effective backend, not config

Display the resolved backend in operator-facing UI, not the raw config value. Use an `_effective_repo_provider()` helper mirroring the key-presence fail-safe in `apply_repo_provider`.
- **Example:** In `src/dashboard_routes/_state_routes.py`, `RepoOverview` read `rt.config.repo_provider` and showed a GLM badge even when `ZAI_API_KEY` was missing, silently falling back to Claude.
- **Why:** Showing the configured dial rather than the actual spawn target hides critical misconfigurations from operators.
