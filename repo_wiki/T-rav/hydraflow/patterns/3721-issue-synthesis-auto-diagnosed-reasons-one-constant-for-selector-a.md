---
id: 3721
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T13:50:49.945549+00:00
status: active
corroborations: 1
supersedes: 3576
---

# AUTO_DIAGNOSED_REASONS: one constant for selector and _auto_diagnose

Define surface reasons that auto-diagnose terminates on as a single `frozenset` constant (`AUTO_DIAGNOSED_REASONS`) in `src/escape_ledger_loop.py`, read by both `select_findings_to_surface` and `_auto_diagnose`.

Example: `AUTO_DIAGNOSED_REASONS = frozenset({SURFACE_REASON_LOW_CONFIDENCE})`; aging-eligible rows are NOT in this set, so they keep reaching humans even when terminally diagnosed.

**Why:** A second source of truth for which reasons are machine-diagnosed would drift, silently suppressing legitimate human surfaces or letting terminal rows leak through.
