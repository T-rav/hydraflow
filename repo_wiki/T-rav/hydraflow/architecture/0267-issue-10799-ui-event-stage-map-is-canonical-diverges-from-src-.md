---
id: 0267
topic: architecture
source_issue: 10799
source_phase: plan
created_at: 2026-07-28T10:31:44.654923+00:00
status: active
corroborations: 1
---

# UI event→stage map is canonical, diverges from src/timeline.py

Rule: The UI's event→stage-key map in `src/ui/src/operator/model/eventStage.js` is UI-canonical and intentionally differs from `src/timeline.py`. Example: backend uses key `merge`, UI uses `merged`; backend files HITL under `review`, UI uses `hitl`. Document the divergence in the shared module's header. **Why:** Mirroring the backend blindly fails guards that expect UI-canonical keys and silently misclassifies `hitl_escalation` events.
