---
id: 1297
topic: gotchas
source_issue: 11126
source_phase: plan
created_at: 2026-08-14T11:53:15.166005+00:00
status: active
corroborations: 1
---

# DISMISSED ledger rows re-enter select_findings_to_surface each tick

A DISMISSED row in `EscapeDiagnosisLedger` never mutates the ledger, so it re-enters `select_findings_to_surface` every tick and consumes the `max_issues_per_tick` filing budget.

- This is pre-existing but becomes louder when `_auto_diagnose` drops the `SURFACE_REASON_LOW_CONFIDENCE` gate.
- File as a discovered issue rather than fixing in the same change.

**Why:** Cap starvation silently blocks genuine escapes from being filed because dismissed findings keep eating the per-tick budget.
