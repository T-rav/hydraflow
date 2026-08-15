---
id: 2528
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T06:55:24.243985+00:00
status: superseded
corroborations: 1
supersedes: 2408
superseded_by: 2651
---

# classify_diagnosis must never dismiss CONFIRMED escape rows

`classify_diagnosis` in `src/escape/auto_diagnose.py` must scope dismissal to non-CONFIRMED rows only — the machine may never withdraw a confirmed escape on a label alone.

Example: High/medium-confidence rows entering the widened `classify_diagnosis` pass must be checked for confirmation status before dismissing.

**Why:** A label-driven dismissal of a CONFIRMED escape silently erases a real defect.
