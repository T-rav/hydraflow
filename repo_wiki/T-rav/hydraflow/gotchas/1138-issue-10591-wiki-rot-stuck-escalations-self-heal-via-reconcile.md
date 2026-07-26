---
id: 1138
topic: gotchas
source_issue: 10591
source_phase: plan
created_at: 2026-07-26T03:23:10.272120+00:00
status: superseded
corroborations: 1
superseded_by: 1144
---

# wiki-rot-stuck escalations self-heal via reconcile_open; hydraflow-find issues don't

`EscalationReconciler.reconcile_open` auto-closes any `wiki-rot-stuck` escalation whose subject leaves `active_subjects` on the next *complete* `WikiRotDetectorLoop` tick — no new runtime code is needed to clear stale escalations after a detector fix. But issues filed with the `hydraflow-find` + `wiki-rot` labels have no equivalent auto-close path; they stay open forever unless a dedicated audit/close script runs. Confirmed in #10591's plan: only the escalation half needs a test proving self-heal (`tests/scenarios/test_wiki_rot_detector_scenario.py`); the find half needs `scripts/audit_wiki_rot_false_positives.py`.

**Why:** assuming both artifact types (finds vs. escalations) reconcile the same way leads to silently-stuck `hydraflow-find` issues after a bug fix ships.
