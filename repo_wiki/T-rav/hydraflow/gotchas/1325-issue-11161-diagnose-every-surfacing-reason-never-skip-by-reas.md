---
id: 1325
topic: gotchas
source_issue: 11161
source_phase: plan
created_at: 2026-08-14T18:36:34.319367+00:00
status: active
corroborations: 1
---

# Diagnose every surfacing reason — never skip by reason in _auto_diagnose

Remove reason-based pre-filters before passing findings to auto-diagnose. The downstream machinery already handles each resolution type.

- `EscapeLedgerLoop._auto_diagnose` (`src/escape_ledger_loop.py:601`) had `reason != SURFACE_REASON_LOW_CONFIDENCE`, which blocked aging surfaces from machine diagnosis.
- `RESOLVED_ENCODED`, `DISMISSED`, and `INCONCLUSIVE` each route correctly without a reason gate.

**Why:** Pre-filtering strands surfaces that could self-answer, generating false HITL issues for encodings already on disk.
