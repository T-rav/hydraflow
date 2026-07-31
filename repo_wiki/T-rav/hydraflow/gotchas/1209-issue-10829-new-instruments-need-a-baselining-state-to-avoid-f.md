---
id: 1209
topic: gotchas
source_issue: 10829
source_phase: plan
created_at: 2026-07-31T01:09:02.057439+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# New instruments need a baselining state to avoid false-positive first reports

Instruments that detect transitions need `min_baseline_windows` (config field) observations before reporting breaches. With fewer, the report must say "baselining", never "green" or "breach".

- Without a prior snapshot, every ADR looks like a transition.
- Combine with per-tick issue cap (`setpoint_erosion_max_issues_per_tick`) and cross-tick dedup.

**Why:** Filing noise on the first months destroys trust in an instrument whose value is legibility when it fires.
