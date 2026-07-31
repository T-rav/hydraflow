---
id: 1389
topic: patterns
source_issue: 10871
source_phase: review
created_at: 2026-07-31T16:47:39.085954+00:00
status: active
corroborations: 1
---

# Regression tests need behavioral load plus AST guard (wiki 0282)

Regression tests for function renames must include a real behavioral load call plus an AST/grep guard — not a monkeypatch-only structural test.

- `tests/regressions/test_issue_10871.py` follows wiki entry 0282 convention for this exact fix class.

**Why:** Monkeypatch-only tests can pass even when the actual import path is broken, giving false confidence that the rename is safe.
