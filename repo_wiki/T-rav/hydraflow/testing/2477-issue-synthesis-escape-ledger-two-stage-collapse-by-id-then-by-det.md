---
id: 2477
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:50.130691+00:00
status: active
corroborations: 1
supersedes: 2287
---

# Escape ledger two-stage collapse: by id, then by detection_ref

Collapse `escape_ledger.jsonl` rows in two passes: first by id (latest-appended wins), then by `detection_ref` — an `encoded_as != 'none-yet'` row always wins over a bare detector row; otherwise pick strongest confidence, tie-broken by latest.

Example: lives in `src/escape/metrics.py::latest_by_escape`, consumed by `src/escape/ledger.py::read_latest()`.

**Why:** Collapsing by `detection_ref` alone would let a later none-yet detector rerun silently discard a human `append_resolution` row for the same commit.
