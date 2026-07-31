---
id: 0274
topic: architecture
source_issue: 10862
source_phase: plan
created_at: 2026-07-31T02:48:15.326661+00:00
status: active
corroborations: 1
---

# Ban src.-aliased imports in tests/conftest.py

Use an architecture test (`tests/architecture/test_conftest_no_src_alias_imports.py`) to assert `tests/conftest.py` imports no `src.`-aliased module that `src/` code imports bare. Key on modules `src/` imports bare, not a blanket-ban on `src.` prefixes.

**Why:** Dual-importing a module creates two `sys.modules` objects over one file, desynchronizing module-level state like `functools.lru_cache` and singletons, causing silent state leaks between tests.
