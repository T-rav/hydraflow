---
id: 1319
topic: gotchas
source_issue: 11145
source_phase: plan
created_at: 2026-08-14T15:10:07.166200+00:00
status: active
corroborations: 1
---

# Escalation-label SSOT lives in config.py, not hardcoded in loops

All HITL escalation label references in `src/` must derive from `config.py`'s `hitl_escalation_queue_labels` property and `LEGACY_HITL_ESCALATION_LABEL` constant. The only files allowed to contain the bare `"hitl-escalation"` literal are `src/config.py` and `src/prep.py`.

- Readers iterate `config.hitl_escalation_queue_labels` (configured root first, legacy alias appended, deduped, order-stable).
- Writers file under `config.hitl_escalation_label[0]`.
- A grep for the bare literal across `src/` outside those two files is a failure.

**Why:** Hardcoding the label in individual loops caused escalations from `TriageRetryLoop`, `AdrTouchpointAuditorLoop`, and `StagingPromotionLoop` to be invisible to pre-flight when the configured label was renamed.
