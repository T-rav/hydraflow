---
id: 1068
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.555958+00:00
status: active
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
---

# Map legacy bare dedup keys to a specific reason during migration

When splitting a single dedup key into reason-scoped keys, don't let old rows re-fire on deploy. In escape_ledger_loop.py, treat a pre-existing bare surfaced:<id> key as equivalent to the low-confidence reason only — it never satisfies the aging key. New records get properly reason-scoped keys from the start.

**Why:** this prevents a surfacing storm across every previously-surfaced EscapeLedger row the moment the reason-scoped key format ships, while still letting the aging criterion become reachable for those same rows going forward.
