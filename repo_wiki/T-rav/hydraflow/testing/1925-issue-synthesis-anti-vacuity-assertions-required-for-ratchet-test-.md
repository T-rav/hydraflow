---
id: 1925
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T06:59:06.561904+00:00
status: superseded
corroborations: 1
supersedes: 1821
superseded_by: 2052
---

# Anti-vacuity assertions required for ratchet test suites

Every ratchet test suite must include an anti-vacuity assertion: the checked set is non-empty and at least one item passes on merit.

Example: `test_adr0025_symmetric_field_assertions.py` asserts shared return types exist and ≥1 is fully field-asserted. `test_adr0035_toggle_state_coverage.py` asserts the toggle set is non-empty and ≥1 toggle passes both-state coverage.

**Why:** An empty toggle/type set makes the ratchet vacuously green, silently hiding regressions when the codebase changes underneath.
