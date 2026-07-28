---
id: 1350
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T22:47:42.338679+00:00
status: superseded
corroborations: 1
supersedes: 1276
superseded_by: 1425
---

# EscapeLedger is append-only: resolutions are new rows

EscapeLedger (src/escape/ledger.py) is append-only — append_resolution adds a new JSONL line carrying encoded_as; the original row stays on disk forever. Any read path (unresolved(), unencoded_aging, encoded_summary in src/escape_ledger_loop.py) must go through read_latest()/latest_by_id or it double-counts.

Example: existing_ids() must contain the id exactly once after supersession, so a re-tick doesn't re-record.

**Why:** In-place rewrites would erase false-positive history and silently resurface already-resolved escapes on the HITL surface.
