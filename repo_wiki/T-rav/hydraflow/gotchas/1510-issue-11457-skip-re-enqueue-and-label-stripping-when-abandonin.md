---
id: 1510
topic: gotchas
source_issue: 11457
source_phase: plan
created_at: 2026-08-18T12:04:53.781961+00:00
status: active
corroborations: 1
---

# Skip re-enqueue and label stripping when abandoning resolved issues

Rule: when abandoning a resolved issue, do NOT re-enqueue to ready and do NOT strip labels.

- Slot is freed by `_worker`'s `finally` (`release_batch_in_flight` + `_release_claim`).
- `IssueFetcher._is_open` keeps closed issues out of the next refresh.
- `LabelDriftWatcherLoop` (ADR-0088 / #10394) owns label hygiene.

**Why:** Re-enqueuing or stripping labels here duplicates ownership and can race with the watcher loop.
