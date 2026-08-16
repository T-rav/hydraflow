---
id: 1427
topic: gotchas
source_issue: 11306
source_phase: plan
created_at: 2026-08-16T05:13:33.717435+00:00
status: active
corroborations: 1
---

# notice_class and severity are orthogonal on SystemAlertPayload

`SystemAlertPayload.severity` already controls banner colour (`warning`=yellow, else red) in `src/models.py`. `notice_class` (`"blocking"` | `"advisory"`) is a separate routing axis. Absent `notice_class` defaults to `blocking` (fail-loud). **Why:** Reusing `severity` for routing would conflate visual urgency with operational routing, causing advisories to hijack the `SystemAlertBanner` reserved for credit pauses, faults, and HITL.
