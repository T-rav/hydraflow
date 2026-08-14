---
id: 2554
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.355218+00:00
status: active
corroborations: 1
supersedes: 2365
---

# Every registered series needs a paired counter-metric id (#10840)

When registering a series identity in `src/setpoint/series.py`, each must carry a non-empty paired counter-metric id. For example, the enforced-fraction series pairs with ADR coverage / decision rate.

**Why:** Unpaired metrics create blind spots — a drop in enforcement fraction could reflect fewer in-scope ADRs rather than real erosion, and the counter-metric disambiguates the signal.
