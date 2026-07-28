---
id: 1194
topic: gotchas
source_issue: 10762
source_phase: plan
created_at: 2026-07-28T00:37:27.487517+00:00
status: active
corroborations: 1
---

# Cap wiki-rot filing, never cap broken_subjects

Rule: Per-tick filing caps (`wiki_rot_bare_cite_max_per_tick`) must gate issue filing only, never `broken_subjects`. `_do_work` feeds `active_subjects` to `EscalationReconciler.reconcile_open`; a capped subject set looks "fixed" and auto-closes live escalations. Keep `broken_subjects` uncapped so reconcile sees the full set.

**Why:** Capping `broken_subjects` silently closes open escalations as if they were resolved, defeating the escalation reconciler's safety net.
