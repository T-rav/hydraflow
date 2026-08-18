---
id: 2748
topic: testing
source_issue: 11420
source_phase: plan
created_at: 2026-08-18T03:48:25.160821+00:00
status: active
corroborations: 1
---

# Register fake↔real runner pairs via method-floor, not _PORT_FAKE_PAIRS

When adding `FakeLLM` runner pairs to `tests/test_mockworld_fakes_conformance.py`, parametrize a separate test scoped to the intersection of public methods with an explicit required-method floor — do not append to `_PORT_FAKE_PAIRS`.

Floor includes: `evaluate`, `plan`, `run`, `review`, `fix_ci`, `fix_review_findings`, `set_tracing_context`, `clear_tracing_context`, `terminate`.

**Why:** `_PORT_FAKE_PAIRS`'s missing-methods assertion fires on real-runner helpers MockWorld never substitutes (`set_observability`, `build_command`, `PlannerRunner` diagram classmethods).
