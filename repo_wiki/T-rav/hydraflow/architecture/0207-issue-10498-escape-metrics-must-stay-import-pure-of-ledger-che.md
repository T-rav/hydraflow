---
id: 0207
topic: architecture
source_issue: 10498
source_phase: review
created_at: 2026-07-25T09:07:23.395862+00:00
status: active
corroborations: 1
---

# escape.metrics must stay import-pure of ledger (checked rubric item)

`src/escape/metrics.py` (referenced as `escape.metrics`) must not import `ledger` — PR #10525's review explicitly re-verified this as part of its pre-flight rubric to avoid reintroducing an import cycle when touching `EscapeLedger`/`escape_ledger_loop.py`. Any future change wiring metrics into the ledger read path should re-check this direction of import.

**Why:** `ledger` already depends on ledger-adjacent modules; a reverse import from `metrics` back into `ledger` would create a cycle.
