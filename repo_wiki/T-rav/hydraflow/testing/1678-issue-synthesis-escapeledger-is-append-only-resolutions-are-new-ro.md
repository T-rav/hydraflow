---
id: 1678
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T02:43:14.305676+00:00
status: active
corroborations: 1
supersedes: 1595
---

# EscapeLedger is append-only: resolutions are new rows

EscapeLedger (src/escape/ledger.py) is append-only — append_resolution adds a new JSONL line; the original row stays on disk forever. Any read path (unresolved(), unencoded_aging, encoded_summary) must go through read_latest()/latest_by_id or it double-counts.

Example: existing_ids() must contain the id exactly once after supersession.

**Why:** In-place rewrites would erase false-positive history and silently resurface already-resolved escapes on the HITL surface.
