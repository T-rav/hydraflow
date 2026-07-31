---
id: 1807
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T04:20:59.151040+00:00
status: superseded
corroborations: 1
supersedes: 1713
superseded_by: 1912
---

# Instruments must import the authoritative classifier, never reimplement

Any instrument that measures ADR enforcement status must import `adr_conformance.classify_adr_enforcement` (src/adr_conformance.py:464) rather than re-deriving REAL/WEAK/MISSING logic.

- `setpoint/collect.py` calls the classifier and snapshots only its Accepted-only population.
- A population-assertion test pins the known corpus truth (74/78 REAL) to catch filter drift.

**Why:** Reimplementing the classifier with slightly different filtering produces a false-positive headline that contradicts existing findings (e.g. the 44/45-flat result).
