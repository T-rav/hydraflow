---
id: 1081
topic: testing
source_issue: 10574
source_phase: plan
created_at: 2026-07-26T00:21:42.291365+00:00
status: superseded
corroborations: 1
superseded_by: 1085
---

# Escape ledger is append-only: resolutions are new rows, never rewrites

`EscapeLedger.append_resolution` adds a new JSONL line carrying `encoded_as`; the original `none-yet` row for that id stays on disk forever. Any read path (`unresolved()`, `unencoded_aging`, `encoded_summary.unencoded` in `src/escape_ledger_loop.py`) must go through `read_latest()`/`latest_by_id` or it double-counts the same escape id.

**Why:** skipping latest-row dedup silently resurfaces already-resolved escapes on the HITL surface, per [[escape_ledger_supersession_append_only]].
