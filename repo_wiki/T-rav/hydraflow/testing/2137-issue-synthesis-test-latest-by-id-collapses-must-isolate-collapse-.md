---
id: 2137
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T14:26:19.293486+00:00
status: superseded
corroborations: 1
supersedes: 2008
superseded_by: 2282
---

# test_latest_by_id_collapses must isolate collapse basis

In tests/test_escape_ledger.py:494, test_latest_by_id_collapses_to_last_appended_row gives both rows the same detected_at, so it can't distinguish append-position collapse from timestamp collapse.

Example: strengthen with a 3-row chain plus a case where the earlier-position row has a later detected_at, to pin position-based collapse semantics.

**Why:** An ambiguous fixture lets a semantically wrong collapse implementation pass the existing test.
