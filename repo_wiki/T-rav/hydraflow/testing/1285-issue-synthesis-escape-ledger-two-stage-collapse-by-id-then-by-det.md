---
id: 1285
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T20:11:03.430000+00:00
status: superseded
corroborations: 1
supersedes: 1211
superseded_by: 1359
---

# Escape ledger two-stage collapse: by id, then by detection_ref

Collapse escape_ledger.jsonl rows in two passes: first by id (latest-appended wins), then by detection_ref — an `encoded_as != "none-yet"` row always wins over a bare detector row; otherwise pick strongest confidence (high>medium>low), tie-broken by latest.

Example: lives in src/escape/metrics.py::latest_by_escape, consumed by src/escape/ledger.py::read_latest().

**Why:** Collapsing by detection_ref alone would let a later none-yet detector rerun silently discard a human append_resolution row for the same commit.
