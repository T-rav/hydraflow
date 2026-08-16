---
id: 2724
topic: testing
source_issue: 11353
source_phase: plan
created_at: 2026-08-16T14:57:57.978638+00:00
status: active
corroborations: 1
---

# Use it.fails() for self-retiring UI pins; skip/xfail banned in tests/

The architecture guard `tests/architecture/test_no_ignored_active_tests.py` rejects `pytest.mark.skip`/`xfail` in any `tests/**/test*.py`. For a UI pin that should retire when a fix lands, use vitest `it.fails()` — green now, red the moment the fix lands, then remove mechanically. Pair it with a GREEN sibling test sharing the same harness so a bad selector or typo doesn't silently pass the pin.

**Why:** Prevents permanently-skipped tests from accumulating while still holding a failing assertion that self-inverts on fix landing.
