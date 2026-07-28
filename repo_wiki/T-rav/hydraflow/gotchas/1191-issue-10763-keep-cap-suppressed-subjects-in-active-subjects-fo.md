---
id: 1191
topic: gotchas
source_issue: 10763
source_phase: plan
created_at: 2026-07-28T00:17:34.080268+00:00
status: active
corroborations: 1
---

# Keep cap-suppressed subjects in active_subjects for reconcile_open

Per-tick filing caps must bound only `create_issue` calls. Cap-suppressed and dedup-suppressed orphans must remain in `active_subjects` (passed to `reconcile_open`) and in `broken_subjects`, reported via one aggregate WARNING per tick.

Example: With `wiki_rot_detector_max_issues_per_tick=1` and three eligible orphans, `to_file` has one subject, `suppressed_count` is 2, but all three stay in `all_orphan_subjects`. A cap-suppressed orphan's open escalation must not auto-close.

**Why:** Omitting suppressed subjects from `active_subjects` makes `EscalationReconciler.reconcile_open` close live escalations that should stay open.
