---
id: 2805
topic: testing
source_issue: 11947
source_phase: plan
created_at: 2026-09-01T10:45:05.630247+00:00
status: active
corroborations: 1
---

# Gates must raise on unresolvable refs, not pass green

A gate that exits 0 on an unresolvable git ref is worse than no gate — it hides behind a green signal. Reuse `check_deletion_scope.py`'s `BaseUnresolvable` pattern: the `_git` helper raises rather than returning empty output.

- `scripts/check_symbol_drop.py` raises on a bogus `--base` instead of passing.
- CI test pins this: `tests/test_check_symbol_drop.py` asserts an unresolvable base raises.
- This is the #11902 lesson — a sibling gate silently passed green on bad refs.

**Why:** Silent green-on-error gives false confidence that the gate ran and found nothing, when it actually never ran.
