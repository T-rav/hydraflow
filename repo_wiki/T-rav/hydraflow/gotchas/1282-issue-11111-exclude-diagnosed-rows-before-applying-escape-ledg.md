---
id: 1282
topic: gotchas
source_issue: 11111
source_phase: plan
created_at: 2026-08-14T09:08:28.015667+00:00
status: active
corroborations: 1
---

# Exclude diagnosed rows before applying escape_ledger_max_issues_per_tick

`select_findings_to_surface` in `src/escape_ledger_loop.py` must drop terminal rows (via the `already_diagnosed` id set) *before* applying `escape_ledger_max_issues_per_tick`, not after.

- Cap = 1, one dismissed row present → a different eligible escape still gets filed that tick
- If the cap runs first, dismissed rows permanently hold filing slots

**Why:** Applying the cap before exclusion trades a one-tick leak for a permanent budget leak; removing diagnosed rows after the cap would cause `reconcile_open` to auto-close live escalations.
