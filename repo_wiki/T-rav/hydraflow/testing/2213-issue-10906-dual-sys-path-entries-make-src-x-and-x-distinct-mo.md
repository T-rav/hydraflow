---
id: 2213
topic: testing
source_issue: 10906
source_phase: plan
created_at: 2026-07-31T12:53:04.027080+00:00
status: superseded
corroborations: 1
superseded_by: 2338
---

# Dual sys.path entries make src.X and X distinct module objects

When both `<repo>` and `<repo>/src` are on `sys.path` (conftest.py:162-163, `PYTHONPATH=src` in Makefile), `src.telemetry.spans` and `telemetry.spans` load as two separate module objects with independent `_get_tracer` caches and singletons. An autouse fixture clearing one cache leaves the other stale — production code resolves via the bare alias, so tests importing `src.` prefixes reset the wrong object.

**Why:** Cache-clearing fixtures silently become no-ops, causing cross-test OTel/telemetry leakage that only surfaces under xdist loadscope, not serial runs.
