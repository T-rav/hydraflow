---
id: 0050
topic: dependencies
source_issue: 10785
source_phase: plan
created_at: 2026-07-28T09:16:36.126419+00:00
status: active
corroborations: 1
---

# source_to_phase keys map 1:1 to OPERATOR_STAGES; hitl/merged excluded

Phase keys from `source_to_phase` are `triage|plan|implement|review` and map directly onto `OPERATOR_STAGES`. The `hitl` and `merged` phases have no badge in the pipeline rail.

- `PipelineRail.jsx` stage tiles for `hitl`/`merged` must render no cost badge.
- Badges for the four mapped phases carry token + cost data.

**Why:** These two phases are terminal/transitional states with no inference spend; showing an empty or zero badge would imply the stage was cost-free when it simply has no cost data.
