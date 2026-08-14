---
id: 2600
topic: testing
source_issue: 11163
source_phase: plan
created_at: 2026-08-14T18:57:58.285624+00:00
status: active
corroborations: 1
---

# Log one aggregate WARNING per tick, never per sidecar row

When `_surface_findings` in `src/escape_ledger_loop.py` detects unreadable sidecar rows, emit exactly ONE aggregate WARNING per tick using a literal format string (count + ids). Do not emit one warning per row.

- Correct: single log naming all unreadable ids for that tick.
- Wrong: per-row log inside the iteration.

**Why:** Per-row logs flood the idle test and contradict the noise-reduction goal that this entire PR family (#11111/#11137/#11144/#11148) exists to enforce.
