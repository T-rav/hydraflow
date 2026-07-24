---
id: 0431
topic: gotchas
source_issue: 10310
source_phase: plan
created_at: 2026-07-24T04:15:36.841908+00:00
status: superseded
corroborations: 1
superseded_by: 0446
---

# Treat unset diagnosis severity as not-low, not as a free pass, in severity detectors

When classifying issues by diagnosed severity (`state.get_diagnosis_severity`), an issue that was escalated before a diagnose pass ran returns `None` — this must NOT be miscounted as low-severity (e.g. P4) by default; only count it low if it separately carries a configured housekeeping label.

Example: `detect_hitl_low_severity_pileup(issues, threshold=..., housekeeping_labels=...)` classifies low-severity as `severity == P4_HOUSEKEEPING OR has housekeeping label`, explicitly excluding `None`+no-label issues.

**Why:** miscounting undiagnosed issues as low-severity would trigger the pile-up alert on issues that simply haven't been triaged yet, producing false-positive fleet escalations.
