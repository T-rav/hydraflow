---
id: 2672
topic: testing
source_issue: 11302
source_phase: plan
created_at: 2026-08-16T04:43:31.978011+00:00
status: active
corroborations: 1
---

# Clear full credential surface in delenv, not just the primary key

When writing tests that assert a backend 'falls open' on a missing key, clear the *entire* provider key surface, not just the primary API key env.

In `tests/test_llm_provider.py::TestHarnessBackend::test_resolve_harness_env_missing_key_falls_open`, `ZAI_CODING_PLAN_KEY` and `HYDRAFLOW_ZAI_CODING_PLAN_KEY` sit ahead of `ZAI_API_KEY` in the priority chain (#11267). Clearing only `ZAI_API_KEY` leaves the coding-plan key as a fallback, so the test passes without exercising the intended path.

**Why:** Partial `delenv` lists create false-green tests that survive priority-chain reordering.
