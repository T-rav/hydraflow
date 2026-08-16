---
id: 3327
topic: patterns
source_issue: 11306
source_phase: plan
created_at: 2026-08-16T05:13:33.717449+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Split advisory alerts from systemAlert but keep addEvent on both branches

In `HydraFlowContext.jsx` reducer `case 'system_alert'`, route advisory payloads to `advisoryNotices` and blocking payloads to existing `systemAlert`. Both branches must call `addEvent(state, action)` so the event log is unchanged. The alert payload carries no timestamp — stamp `action.timestamp` onto the notice. **Why:** Dropping `addEvent` on the advisory branch silently removes epic-stale events from the audit log.
