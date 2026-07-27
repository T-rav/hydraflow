---
id: 1155
topic: gotchas
source_issue: 10654
source_phase: plan
created_at: 2026-07-26T16:24:44.376104+00:00
status: active
corroborations: 1
---

# Pin live SHA bytes in regression tests via raw JSONL, not append

Regression tests for escape-ledger shape should write raw JSONL lines directly to a temp file, not call `EscapeLedger.append`.

- `tests/regressions/test_issue_10654.py` seeds the four live rows (`ee56677…` and `055267e…`, each `bug-issue`/low + `regression-pin`/medium) as raw bytes so the on-disk file under test matches production.
- This pins the exact failure shape independent of detector or append logic.

**Why:** Going through `append` would exercise the same code path that produced the bug, hiding byte-level regressions in the live ledger file.
