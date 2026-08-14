---
id: 0306
topic: architecture
source_issue: 11102
source_phase: plan
created_at: 2026-08-14T07:12:44.487636+00:00
status: active
corroborations: 1
---

# Prose count validators check counts only, not enumeration completeness

`validate_prose_counts` in `scripts/gates/validate.py` must compare the stated "N required checks" against `len(resolve_contexts(branch))` — nothing more.

- The `main` row in the README says "14 required checks **including** (…4 named)" — partial enumeration by design.
- The staging row's parenthetical claims completeness.
- Forcing main to enumerate all 14 to satisfy a completeness check would break the control row and produce false violations on unrelated README edits.

**Why:** Enumeration asymmetry between rows means a completeness guard false-positives on the intentionally partial `main` row, leading to the guard being weakened or removed.
