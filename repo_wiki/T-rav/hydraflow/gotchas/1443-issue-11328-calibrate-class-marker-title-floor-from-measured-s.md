---
id: 1443
topic: gotchas
source_issue: 11328
source_phase: plan
created_at: 2026-08-16T09:56:55.839235+00:00
status: active
corroborations: 1
---

# Calibrate CLASS_MARKER_TITLE_FLOOR from measured sibling-pair scores

Set `CLASS_MARKER_TITLE_FLOOR` in `src/find_class_key.py` from measured sibling-pair affinity scores in `test_issue_11292.py`, never from a new test's expectation.

- Tightest real pair in the #11292 families scores ≈0.20 → floor must be ≤0.15.
- Run `test_issue_11292.py` before and after changing the floor.

**Why:** A floor set above the tightest real pair breaks `test_issue_11292.py`, which must pass unmodified across all find-class changes.
