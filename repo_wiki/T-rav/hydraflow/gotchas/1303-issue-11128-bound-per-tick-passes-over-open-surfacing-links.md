---
id: 1303
topic: gotchas
source_issue: 11128
source_phase: plan
created_at: 2026-08-14T12:04:30.040494+00:00
status: active
corroborations: 1
---

# Bound per-tick passes over OPEN surfacing links

Any pass that iterates OPEN surfacing links in `src/escape_ledger_loop.py` must be batch-bounded by `escape_ledger_max_issues_per_tick`, skip terminal ids, and emit one aggregate log line — not one per link.

Run the pass before `_resolve_range`'s quiet-tick early exits (per the #10577 rationale) and before `_reconcile_surfaced_issues` so closes happen in the same tick.

**Why:** Unbounded passes run a git grep + label read per open link every tick forever, burning API budget on links that never resolve.
