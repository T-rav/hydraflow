---
id: 0216
topic: architecture
source_issue: 10574
source_phase: plan
created_at: 2026-07-26T00:21:42.291376+00:00
status: active
corroborations: 1
---

# escape_ledger.jsonl filename literal was scattered across 3 modules

The ledger filename string was duplicated as private constants in `src/escape_ledger_loop.py` (`_LEDGER_FILENAME`) and `src/sampled_audit_loop.py` (`_ESCAPE_LEDGER_FILENAME`). Fix: promote a single public `LEDGER_FILENAME = "escape_ledger.jsonl"` in `src/escape/ledger.py` (no leading underscore, since it's now imported cross-module) and point both loops at it.

**Why:** concept-scatter of a literal across loops means a future rename only updates one copy silently — same failure shape as the `_LEDGER_FILENAME`/`_ESCAPE_LEDGER_FILENAME` split found here.
