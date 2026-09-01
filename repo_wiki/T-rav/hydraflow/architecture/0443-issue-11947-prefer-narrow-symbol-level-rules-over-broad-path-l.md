---
id: 0443
topic: architecture
source_issue: 11947
source_phase: plan
created_at: 2026-09-01T10:45:05.630272+00:00
status: active
corroborations: 1
---

# Prefer narrow symbol-level rules over broad path-level blocks

Choose the narrowest rule form enforceable at 0% false positives. The broad rule "block `Write` to any un-Read tracked path" carried 6/14 = 42% FP (sibling #11902). The narrow rule "block `Write` when a tracked `.py` loses a public module-level symbol another tracked file imports by name" measured 0/20 = 0% FP over 400 commits.

- Measured evidence goes in the module docstring, `check_deletion_scope.py`-style.
- ADR-0089 Rule 3: promotion is manual — scope stays one mirror at a time.

**Why:** A 42%-FP rule gets disabled or ignored; a 0%-FP rule stays on and catches the real incident.
