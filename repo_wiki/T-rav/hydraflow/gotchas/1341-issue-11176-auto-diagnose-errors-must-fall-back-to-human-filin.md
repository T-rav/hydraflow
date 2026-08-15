---
id: 1341
topic: gotchas
source_issue: 11176
source_phase: plan
created_at: 2026-08-14T22:35:54.596987+00:00
status: active
corroborations: 1
---

# Auto-diagnose errors must fall back to human filing in escape ledger

Rule: When `_auto_diagnose` fails for a finding in `escape_ledger_loop.py`, file the human issue as if diagnosis never ran. With `escape_ledger_auto_diagnose_enabled=False`, the tick must be byte-equivalent to pre-diagnosis behaviour.

Example: An aging finding whose diagnosis throws still appears as an open surfacing link to a human.

**Why:** Machine diagnosis is an optimization, not a gate — a broken diagnostic must never suppress a genuine escape from reaching a human.
