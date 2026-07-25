---
id: 1007
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.605608+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
---

# Map legacy bare dedup keys to a specific reason during migration

When splitting a single dedup key into reason-scoped keys, don't let old rows re-fire on deploy. In escape_ledger_loop.py, treat a pre-existing bare surfaced:<id> key as equivalent to the low-confidence reason only — it never satisfies the aging key. New records get properly reason-scoped keys from the start.

**Why:** This prevents a surfacing storm across every previously-surfaced EscapeLedger row the moment the reason-scoped key format ships, while still letting the aging criterion become reachable for those same rows going forward.
