---
id: 1598
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T01:04:04.399253+00:00
status: active
corroborations: 1
supersedes: 1516
---

# Map legacy bare dedup keys to specific reason in migration

When splitting a single dedup key into reason-scoped keys, treat pre-existing bare keys as equivalent to the low-confidence reason only — they never satisfy the aging key.

Example: in escape_ledger_loop.py, a pre-existing bare `surfaced:<id>` key never satisfies the aging criterion; new records get properly reason-scoped keys from the start.

**Why:** Prevents a surfacing storm across every previously-surfaced EscapeLedger row the moment the reason-scoped key format ships.
