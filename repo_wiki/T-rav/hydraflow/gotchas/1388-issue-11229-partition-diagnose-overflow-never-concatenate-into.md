---
id: 1388
topic: gotchas
source_issue: 11229
source_phase: plan
created_at: 2026-08-15T07:12:37.006254+00:00
status: active
corroborations: 1
---

# Partition diagnose overflow; never concatenate into ask budget

Only a diagnosed finding may spend the ask budget. `_auto_diagnose` must return `(residue, deferred)` — `residue` holds rows it actually attempted (INCONCLUSIVE, or diagnose-failed kept fail-safe), and never-attempted overflow is `deferred` (no issue, no fingerprint spend, no terminal verdict).

- `src/escape_ledger_loop.py:658-661`: the `index >= max_diagnoses` branch previously appended overflow into `residue`, which fed `apply_ask_budget`.
- Fix: `_surface_findings` passes only `residue` to `apply_ask_budget`; deferred rows stay eligible for a later tick.

**Why:** Concatenating overflow into the ask budget files human HITL issues for escapes the diagnoser never attempted (the #11229 defect).
