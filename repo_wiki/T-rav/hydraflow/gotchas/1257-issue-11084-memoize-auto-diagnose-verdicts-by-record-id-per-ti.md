---
id: 1257
topic: gotchas
source_issue: 11084
source_phase: plan
created_at: 2026-08-14T05:53:19.138422+00:00
status: active
corroborations: 1
---

# Memoize auto-diagnose verdicts by record.id per tick

`select_findings_to_surface` snapshots both pairs of a doubly-eligible row *before* diagnosis runs, so a row resolved via its low-confidence pair is still filed under its aging pair. Diagnose each `record.id` at most once per tick and share the verdict across pairs.
- Memoize failures as `INCONCLUSIVE` (fail-safe) so a diagnoser that raises still pages a human for every pair.
**Why:** Without per-id memoization the same escape is diagnosed N times and the second pair re-files a row the first pair already resolved.
