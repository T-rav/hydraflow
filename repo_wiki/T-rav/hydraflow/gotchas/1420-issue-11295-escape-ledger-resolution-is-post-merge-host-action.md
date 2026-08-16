---
id: 1420
topic: gotchas
source_issue: 11295
source_phase: plan
created_at: 2026-08-16T02:40:08.127274+00:00
status: active
corroborations: 1
---

# Escape ledger resolution is post-merge host action, never in the diff

The escape ledger is gitignored (`.gitignore:222`), so `make escape-resolve ARGS="..."` is a host-local runtime action, never part of a PR diff. Resolving before merge causes `EscapeLedgerLoop` to auto-close the tracking issue while the defect is still live.

Run resolution only after the fix merges, then verify via `make escape-list` that the id disappears on the next loop tick.

**Why:** Premature resolution auto-closes the issue, hiding an unfixed defect from the aging surface and stopping re-firing alerts.
