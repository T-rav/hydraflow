---
id: 3724
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T13:50:50.003843+00:00
status: superseded
corroborations: 1
supersedes: 3579
superseded_by: 3869
---

# pick_refine_order must not read row position as rank

When a scorecard sort serves display only, do not reuse it for decisions — `pick_refine_order` in `src/prompt_efficiency.py` builds its own ranking.

Example: Tier 1: well-sampled rows (≥ `MIN_WINDOW_CALLS`) by descending `cost_per_call`; Tier 2: under-sampled by lifetime average; Tier 3: no telemetry row — stable original order.

**Why:** Row position conflates sample quality with measured rate, so a single heavy-tailed draw can hijack the weekly refine cap.
