---
id: 0953
topic: testing
source_issue: 10498
source_phase: review
created_at: 2026-07-25T09:07:23.395854+00:00
status: active
corroborations: 1
---

# test_latest_by_id_collapses_to_last_appended_row doesn't isolate collapse basis

In `tests/test_escape_ledger.py:494`, `test_latest_by_id_collapses_to_last_appended_row` gives both rows the same `detected_at`, so it can't tell whether `read_latest()` collapses by append position or by timestamp — a regression that flips the collapse key would still pass. Strengthen with a 3-row chain plus a case where the earlier-position row has a *later* `detected_at`, to pin position-based (not timestamp-based) collapse semantics.

**Why:** an ambiguous fixture lets a semantically wrong collapse implementation pass the existing test, akin to [[weak_dict_get_default_assertion]].
