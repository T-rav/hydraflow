---
id: 2749
topic: testing
source_issue: 11420
source_phase: plan
created_at: 2026-08-18T03:48:25.160841+00:00
status: active
corroborations: 1
---

# Resolve FakeLLM fake runners off FakeLLM() in conformance tests

In `tests/test_mockworld_fakes_conformance.py`, access fake runners as attributes of a constructed `FakeLLM()` instance — never import `_FakeTriageRunner`, `_FakePlannerRunner`, etc. across modules.

**Why:** Cross-module `_`-prefixed imports break encapsulation and couple the test to internal class names; `FakeLLM()` exposes the same objects through its public attribute surface.
