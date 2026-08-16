---
id: 0393
topic: architecture
source_issue: 11355
source_phase: plan
created_at: 2026-08-16T15:26:00.442041+00:00
status: active
corroborations: 1
---

# Access private symbols via monkeypatch in tests, never add public aliases

Rule: Module-private symbols like `_extract_metric` and `_METRIC_DESCRIPTIONS` in `src/factory_health.py` stay private. Tests reach them via `monkeypatch` inside the test function — that is test-side patching, not a cross-module import.

- Do not add a public alias or `__all__` entry to accommodate tests.
- This applies to mutation-kill tests that need to patch private functions.

**Why:** Exposing internals for test convenience erodes the module boundary and invites production code to depend on implementation details.
