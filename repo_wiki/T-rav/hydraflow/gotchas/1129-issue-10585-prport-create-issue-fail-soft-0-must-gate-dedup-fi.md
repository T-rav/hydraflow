---
id: 1129
topic: gotchas
source_issue: 10585
source_phase: plan
created_at: 2026-07-26T02:30:26.057522+00:00
status: active
corroborations: 1
---

# PRPort.create_issue fail-soft 0 must gate dedup fingerprint writes

`create_issue` (src/ports.py:366, src/pr_manager.py) is documented fail-soft: it returns `0` instead of raising on failure. Any caller that writes a one-shot dedup fingerprint after calling it must check the return value first — `EscapeLedgerLoop._surface_findings` (src/escape_ledger_loop.py:409) previously wrote the `surfaced:<reason>:<id>` fingerprint unconditionally, permanently burning the retry budget for issues that were never actually created. Bind the return, and on falsy value, log a warning and `continue` before the `set_all` dedup write so the finding re-surfaces next tick.
**Why:** treating a fail-soft `0` as success silently and permanently drops findings that should have been retried.
