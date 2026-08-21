---
id: 0272
topic: dependencies
source_issue: 11458
source_phase: plan
created_at: 2026-08-18T12:25:44.377224+00:00
status: superseded
corroborations: 1
superseded_by: 0290
---

# Re-export leaf utilities through phase_utils for regression pin compatibility

Regression tests pin `src/phase_utils.py` as the import surface for shared predicates. When a zero-dependency leaf module (e.g., `src/issue_state.py`) owns a predicate like `issue_state_is_resolved`, re-export it from `src/phase_utils.py` with `# noqa: F401` so the pin resolves.

**Why:** The regression test imports from `phase_utils` by name; moving the definition to a leaf without re-exporting breaks the pin's import statement.
