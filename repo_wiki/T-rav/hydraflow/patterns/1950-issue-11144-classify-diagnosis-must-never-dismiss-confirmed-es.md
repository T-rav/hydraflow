---
id: 1950
topic: patterns
source_issue: 11144
source_phase: plan
created_at: 2026-08-14T14:39:13.298198+00:00
status: active
corroborations: 1
---

# classify_diagnosis must never dismiss CONFIRMED escape rows

When widening auto-diagnose to all surfacing reasons, `classify_diagnosis` in `src/escape/auto_diagnose.py` must scope dismissal to non-CONFIRMED rows only. The machine may never withdraw a confirmed escape on a label alone.

- High/medium-confidence rows now enter `classify_diagnosis` as part of the widened pass — check the row's confirmation status before dismissing.

**Why:** A label-driven dismissal of a CONFIRMED escape silently erases a real defect.
