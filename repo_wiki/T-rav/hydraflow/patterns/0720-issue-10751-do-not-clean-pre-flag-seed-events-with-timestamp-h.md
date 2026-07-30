---
id: 0720
topic: patterns
source_issue: 10751
source_phase: plan
created_at: 2026-07-27T23:15:11.981981+00:00
status: superseded
corroborations: 1
superseded_by: 0776
---

# Do not clean pre-flag seed events with timestamp heuristics

Events persisted before the `seeded` flag was added carry no marker and will keep inflating tallies until they age out of the history window. State this in the PR. Do not add a timestamp heuristic to retroactively 'clean' them.

Affected tallies: `src/fitness_scorecard_loop.py`, `src/trust_fleet_sanity_loop.py`, `src/dashboard_routes/_cost_rollups.py`, `src/ui/src/operator/model/vitals.js`.

**Why:** Timestamp heuristics risk false-positives on legitimate old events; natural aging is the safe boundary.
