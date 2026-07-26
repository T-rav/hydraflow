---
id: 1131
topic: gotchas
source_issue: 10585
source_phase: plan
created_at: 2026-07-26T02:30:26.057570+00:00
status: active
corroborations: 1
---

# DedupStore set_all writes must skip-not-abort on partial batch failure

When `EscapeLedgerLoop._surface_findings` batches multiple fingerprints into one `set_all` dedup call, a single failed `create_issue` in that tick must only skip that entry's fingerprint — other successful filings in the same batch still get recorded. Don't wrap the whole `set_all` call in a guard that aborts on the first failure.
**Why:** aborting the whole batch on one fail-soft return would re-surface already-successfully-filed escapes and double-file issues on the next tick.
