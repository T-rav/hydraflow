---
id: 0776
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T11:16:04.391087+00:00
status: superseded
corroborations: 1
supersedes: 0720
superseded_by: 0832
---

# Do not clean pre-flag seed events with timestamp heuristics

Events persisted before the `seeded` flag was added carry no marker and will keep inflating tallies until they age out of the history window. State this in the PR. Do not add a timestamp heuristic to retroactively 'clean' them.

Affected tallies: `src/fitness_scorecard_loop.py`, `src/trust_fleet_sanity_loop.py`, `src/dashboard_routes/_cost_rollups.py`, `src/ui/src/operator/model/vitals.js`.

**Why:** Timestamp heuristics risk false-positives on legitimate old events; natural aging is the safe boundary.
