---
id: 0346
topic: architecture
source_issue: 11186
source_phase: review
created_at: 2026-08-15T02:28:30.947505+00:00
status: active
corroborations: 1
---

# Place shared test support modules at tests/ root, not regressions/

Place shared test support modules at `tests/` root with underscore-prefixed names (e.g., `tests/_adr_pin_support.py`), not under `tests/regressions/`. The collection guard `tests/regressions/test_issue_9801_collection.py` enforces structural rules on files in that subdirectory and will reject support modules.

**Why:** Placing support code under `tests/regressions/` risks collection-test failures; a `tests/`-root path with a non-`test_` prefix stays outside pytest's default collection while remaining importable by test files.
