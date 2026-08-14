---
id: 1943
topic: patterns
source_issue: 11137
source_phase: plan
created_at: 2026-08-14T13:57:19.247679+00:00
status: active
corroborations: 1
---

# AUTO_DIAGNOSED_REASONS: one constant for selector and _auto_diagnose

Define the set of surface reasons that auto-diagnose terminates on as a single public `frozenset` constant (`AUTO_DIAGNOSED_REASONS`) in `src/escape_ledger_loop.py`, read by both `select_findings_to_surface` and `_auto_diagnose`.
- Currently `AUTO_DIAGNOSED_REASONS = frozenset({SURFACE_REASON_LOW_CONFIDENCE})`.
- Aging-eligible rows are NOT in this set, so they keep reaching humans even when terminally diagnosed.
**Why:** A second source of truth for which reasons are machine-diagnosed would drift, silently suppressing legitimate human surfaces or letting terminal rows leak through.
