---
id: 1428
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T00:21:29.144712+00:00
status: superseded
corroborations: 1
supersedes: 1353
superseded_by: 1516
---

# Map legacy bare dedup keys to specific reason in migration

When splitting a single dedup key into reason-scoped keys, treat pre-existing bare keys as equivalent to the low-confidence reason only — they never satisfy the aging key.

Example: in escape_ledger_loop.py, a pre-existing bare `surfaced:<id>` key never satisfies the aging criterion; new records get properly reason-scoped keys from the start.

**Why:** Prevents a surfacing storm across every previously-surfaced EscapeLedger row the moment the reason-scoped key format ships, while still letting the aging criterion become reachable going forward.
