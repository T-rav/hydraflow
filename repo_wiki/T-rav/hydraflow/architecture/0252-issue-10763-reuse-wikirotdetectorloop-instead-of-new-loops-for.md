---
id: 0252
topic: architecture
source_issue: 10763
source_phase: plan
created_at: 2026-07-28T00:17:34.080235+00:00
status: active
corroborations: 1
---

# Reuse WikiRotDetectorLoop instead of new loops for wiki passes

Put new wiki-health passes inside the existing `WikiRotDetectorLoop` rather than registering a new loop. A new loop costs an ADR, registration, and a fitness contract — the existing loop already carries ADR-0049's `enabled_cb` kill-switch, worker `wiki_rot_detector`, dedup, attempt counters, and `EscalationReconciler`.

Example: `_lesson_coverage_pass(slug)` is called from `_do_work` after `_tick_repo`, gated by `is_self`, and merges its subjects into `active_subjects` before `reconcile_open`. Reusing the existing escalation title grammar means `_parse_escalation_subject` needs no change.

**Why:** Avoids duplicating safety infrastructure and ADR overhead for passes that share the same tick lifecycle and escalation semantics.
