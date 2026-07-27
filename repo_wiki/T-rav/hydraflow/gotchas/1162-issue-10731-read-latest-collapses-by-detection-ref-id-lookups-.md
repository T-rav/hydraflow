---
id: 1162
topic: gotchas
source_issue: 10731
source_phase: plan
created_at: 2026-07-27T18:39:53.932333+00:00
status: active
corroborations: 1
---

# read_latest() collapses by detection_ref; id lookups need read_latest_index()

When resolving an escape id to a ledger row, use `EscapeLedger.read_latest_index()`, not `read_latest()`. The latter collapses sibling rows by `detection_ref` (since #10676), so a folded-away id returns nothing.

Example: `EscapeLedgerLoop._reconcile_surfaced_issues` builds `answered_surfacings` from `read_latest_index()` so both sibling ids map to the surviving row.

**Why:** A surfacing link holding the losing sibling's id silently skips reconciliation, leaving its HITL issue open forever.
