---
id: 0282
topic: architecture
source_issue: 10871
source_phase: plan
created_at: 2026-07-31T06:30:13.825343+00:00
status: active
corroborations: 1
---

# Regression tests pin anti-patterns with real loads + grep guards

New regression tests under `tests/regressions/test_issue_*.py` should combine a real behavioural load (no stubs, no monkeypatch) with an architectural grep that the anti-pattern cannot return. Example from `tests/regressions/test_issue_10871.py`: real `load_audit_module()` yields non-empty `PROMPT_REGISTRY`, plus a scan that no file under `tests/` or `src/` imports `_load_audit_module`.

**Why:** Behaviour alone confirms the fix works today; the grep guard prevents the anti-pattern from silently returning in a future refactor.
