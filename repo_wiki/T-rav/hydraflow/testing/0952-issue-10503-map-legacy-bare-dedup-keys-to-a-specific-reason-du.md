---
id: 0952
topic: testing
source_issue: 10503
source_phase: plan
created_at: 2026-07-25T02:16:20.035331+00:00
status: active
corroborations: 1
---

# Map legacy bare dedup keys to a specific reason during migration

When splitting a single dedup key into reason-scoped keys, don't let old rows re-fire on deploy. In `escape_ledger_loop.py`, treat a pre-existing bare `surfaced:<id>` key as equivalent to the low-confidence reason only — it never satisfies the aging key. New records get properly reason-scoped keys from the start.

**Why:** This prevents a surfacing storm across every previously-surfaced EscapeLedger row the moment the reason-scoped key format ships, while still letting the aging criterion become reachable for those same rows going forward.
