---
id: 1292
topic: gotchas
source_issue: 11117
source_phase: plan
created_at: 2026-08-14T10:58:30.492153+00:00
status: active
corroborations: 1
---

# Wire alert issue types through EscalationReconciler for dedup and re-file

Each alert issue type in `skill_prompt_eval_loop.py` needs its own label, key-prefix, title/subject helpers, and an `EscalationReconciler` instance beside `_inefficiencies`, including a `reconcile_closed()` call. This yields exactly one issue per broken source until hand-closed, then allows re-filing on the next tick.
- Template: the `_inefficiency_*` helper set and `_inefficiencies` reconciler
- New: `prompt-zero-usage` label / key-prefix / title / subject + third reconciler
**Why:** Without reconciliation, either dedup never releases after close (permanent silence) or duplicate issues pile up every tick.
