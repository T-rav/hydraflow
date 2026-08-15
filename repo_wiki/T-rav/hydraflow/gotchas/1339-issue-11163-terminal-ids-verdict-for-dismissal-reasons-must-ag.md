---
id: 1339
topic: gotchas
source_issue: 11163
source_phase: review
created_at: 2026-08-14T23:12:52.334741+00:00
status: active
corroborations: 1
---

# terminal_ids/verdict_for/dismissal_reasons must agree on unparseable rows

These three sidecar-reading methods must classify unparseable rows identically. A row that `terminal_ids()` treats as terminal but `verdict_for()` maps to `None` is a silent-escape defect. Pin this with regression tests in `tests/regressions/test_issue_11163.py` that assert all three return consistent results for the same unparseable input.

**Why:** Divergence between these methods lets a bug silently escape re-diagnosis and dismissal tracking.
