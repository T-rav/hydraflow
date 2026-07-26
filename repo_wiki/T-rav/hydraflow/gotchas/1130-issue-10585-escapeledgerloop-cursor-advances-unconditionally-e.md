---
id: 1130
topic: gotchas
source_issue: 10585
source_phase: plan
created_at: 2026-07-26T02:30:26.057561+00:00
status: superseded
corroborations: 1
superseded_by: 1144
---

# EscapeLedgerLoop cursor advances unconditionally even on filing failure

`set_escape_ledger_last_processed_sha` in `EscapeLedgerLoop` is deliberately called regardless of whether individual `create_issue` calls in the tick succeeded. A filing failure must not roll back the cursor — only the reason-scoped `surfaced:<reason>:<id>` fingerprint is skipped, not cursor progress. Similarly, the per-tick cap (`escape_ledger_max_issues_per_tick`) still consumes a slot on a failed attempt by design; don't add cap-refund logic.
**Why:** conflating cursor/cap bookkeeping with per-issue filing success would either reprocess the whole SHA range or let one failure starve the cap indefinitely.
