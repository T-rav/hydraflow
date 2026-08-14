---
id: 1948
topic: patterns
source_issue: 11140
source_phase: plan
created_at: 2026-08-14T14:36:07.424525+00:00
status: active
corroborations: 1
---

# pick_refine_order must not read row position as rank

When a scorecard sort serves a display purpose, do not reuse it for decisions. `compute_skill_efficiency` keeps its worst-first sort for rendering; `pick_refine_order` in `src/prompt_efficiency.py` builds its own two-tier ranking instead.

- Tier 1: well-sampled rows (effective sample ≥ `MIN_WINDOW_CALLS`) by descending `cost_per_call`
- Tier 2: under-sampled rows by lifetime average (`est_cost_usd / calls`)
- Tier 3: no telemetry row — stable original order

**Why:** Row position conflates sample quality with measured rate, so a single heavy-tailed draw can hijack the weekly refine cap.
