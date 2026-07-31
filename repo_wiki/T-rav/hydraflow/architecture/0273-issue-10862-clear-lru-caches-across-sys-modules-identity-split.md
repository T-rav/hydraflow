---
id: 0273
topic: architecture
source_issue: 10862
source_phase: plan
created_at: 2026-07-31T02:48:15.326599+00:00
status: active
corroborations: 1
---

# Clear lru_caches across sys.modules identity splits

When `tests/conftest.py` puts both `<repo>` and `<repo>/src` on `sys.path`, a module like `telemetry.spans` can exist as both `telemetry.spans` and `src.telemetry.spans` in `sys.modules`. Clearing an `lru_cache` on one will not clear the other. Implement public `reset_tracer_cache()` in `src/telemetry/spans.py` that iterates all `sys.modules` entries ending in `telemetry.spans`.

**Why:** Production code imports the bare path, tests import the `src.` path; clearing only the test alias leaves production bound to a dead OpenTelemetry provider (e.g., abandoned `FakeHoneycomb`).
