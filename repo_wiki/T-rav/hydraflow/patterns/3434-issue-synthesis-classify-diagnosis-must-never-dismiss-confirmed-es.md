---
id: 3434
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T08:05:58.049335+00:00
status: active
corroborations: 1
supersedes: 3297
---

# classify_diagnosis must never dismiss CONFIRMED escape rows

`classify_diagnosis` in `src/escape/auto_diagnose.py` must scope dismissal to non-CONFIRMED rows only — the machine may never withdraw a confirmed escape on a label alone.

Example: High/medium-confidence rows entering the widened `classify_diagnosis` pass must be checked for confirmation status before dismissing.

**Why:** A label-driven dismissal of a CONFIRMED escape silently erases a real defect.
