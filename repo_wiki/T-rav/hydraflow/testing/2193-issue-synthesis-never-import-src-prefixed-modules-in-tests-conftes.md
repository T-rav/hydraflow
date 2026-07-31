---
id: 2193
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T14:26:19.433850+00:00
status: active
corroborations: 1
supersedes: 2064
---

# Never import src.-prefixed modules in tests/conftest.py

Never import from `src.` prefix in `tests/conftest.py`. Production code imports modules like `telemetry.spans` as bare aliases; importing `src.telemetry.spans` creates a separate module object where `a is b` → `False`.

Example: A fixture calling `_get_tracer.cache_clear()` on the conftest-side `src.telemetry.spans` alias clears the wrong cache, leaving the production-side cache polluted across tests. `tests/regressions/test_issue_10885.py` AST-parses `build_credentials` to enforce this pattern.

**Why:** Cache/fixture clears silently miss their target, making test-boundary resets ineffective and producing order-dependent failures under xdist.
