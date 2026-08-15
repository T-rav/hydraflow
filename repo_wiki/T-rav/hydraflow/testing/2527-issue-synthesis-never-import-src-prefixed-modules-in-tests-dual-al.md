---
id: 2527
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:50.947287+00:00
status: active
corroborations: 1
supersedes: 2338
---

# Never import src.-prefixed modules in tests — dual alias splits objects

Never import from `src.` prefix in `tests/` — when both `<repo>` and `<repo>/src` are on `sys.path` (conftest.py:162-163, `PYTHONPATH=src`), `src.telemetry.spans` and `telemetry.spans` load as separate module objects with independent `_get_tracer` caches.

Example: a fixture calling `_get_tracer.cache_clear()` on the conftest-side `src.telemetry.spans` alias clears the wrong cache, leaving the production-side cache polluted. `tests/regressions/test_issue_10885.py` AST-parses `build_credentials` to enforce this.

**Why:** Cache/fixture clears silently miss their target, making test-boundary resets ineffective and producing order-dependent failures under xdist.
