---
id: 2224
topic: testing
source_issue: 10915
source_phase: plan
created_at: 2026-07-31T15:36:39.647869+00:00
status: superseded
corroborations: 1
superseded_by: 2365
---

# Every registered series needs a paired counter-metric id (#10840)

When registering a series identity in `src/setpoint/series.py`, each must carry a non-empty paired counter-metric id. For example, the enforced-fraction series pairs with ADR coverage / decision rate.

**Why:** Unpaired metrics create blind spots — a drop in enforcement fraction could reflect fewer in-scope ADRs rather than real erosion, and the counter-metric disambiguates the signal.
