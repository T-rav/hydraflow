---
id: 0837
topic: gotchas
source_issue: 10499
source_phase: plan
created_at: 2026-07-25T01:53:00.854351+00:00
status: stale
corroborations: 1
stale_reason: source issue #10499 closed
---

# Escape-ledger fixes close via forward classification, not history rewrite

When fixing a misclassification bug in `src/escape/detect.py`, leave already-written ledger rows alone — `detection_source="bug-issue"` rows written before the fix stay as-is; only commits processed after the fix get correct classification. Escape `bug-issue:055267e7b2b7` in the `EscapeLedger` closes by the detector producing correct output going forward, not by mutating the historical row.
**Why:** consistent with [[escape_ledger_supersession_append_only]] — the ledger is append-only, so retroactive correction would violate its last-row-wins terminal-state model.
