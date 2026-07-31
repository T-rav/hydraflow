---
id: 0294
topic: architecture
source_issue: 10913
source_phase: plan
created_at: 2026-07-31T13:38:55.527452+00:00
status: active
corroborations: 1
---

# No cross-module `_`-prefixed imports — wrap in public accessors

Rule: Never import a `_`-prefixed symbol from another `src/` module. Create a public accessor that wraps the private function.

Example: `src/telemetry/spans.py` exposes `reset_tracer_cache()` wrapping `_get_tracer.cache_clear()`, rather than having `src/mockworld/fakes/fake_honeycomb.py` import `_get_tracer` directly.

**Why:** The repo enforces this via static guards (ruff F401 + #10906 import guard); `_`-prefixed cross-module imports trip CI and signal leaked implementation details.
