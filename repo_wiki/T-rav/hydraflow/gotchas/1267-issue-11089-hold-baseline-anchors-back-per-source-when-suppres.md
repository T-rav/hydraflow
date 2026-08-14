---
id: 1267
topic: gotchas
source_issue: 11089
source_phase: plan
created_at: 2026-08-14T06:37:49.577182+00:00
status: active
corroborations: 1
---

# Hold baseline anchors back per-source when suppressing low-volume sources

When a detector suppresses a low-volume source, the loop must carry that source's baseline entry forward rather than advancing or clearing it. In `skill_prompt_eval_loop._consume_efficiency_telemetry`, replace unconditional `set_prompt_efficiency_baseline(totals_by_source)` with a per-source carry-forward map: advance only when the window was judgeable, no prior entry existed, or counters reset (negative delta → re-anchor); otherwise carry the prior entry. The state writer stays dumb — the loop owns the decision.

**Why:** Wholesale baseline advancement on every tick makes a muted source permanently unjudgeable — the #9841 failure mode.
