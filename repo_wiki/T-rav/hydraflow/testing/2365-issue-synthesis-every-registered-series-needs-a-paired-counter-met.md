---
id: 2365
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:37.143926+00:00
status: active
corroborations: 1
supersedes: 2224
---

# Every registered series needs a paired counter-metric id (#10840)

When registering a series identity in `src/setpoint/series.py`, each must carry a non-empty paired counter-metric id. For example, the enforced-fraction series pairs with ADR coverage / decision rate.

**Why:** Unpaired metrics create blind spots — a drop in enforcement fraction could reflect fewer in-scope ADRs rather than real erosion, and the counter-metric disambiguates the signal.
