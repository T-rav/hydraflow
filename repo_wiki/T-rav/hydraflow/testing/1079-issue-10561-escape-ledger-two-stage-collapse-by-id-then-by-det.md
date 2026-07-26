---
id: 1079
topic: testing
source_issue: 10561
source_phase: plan
created_at: 2026-07-25T23:57:26.301208+00:00
status: active
corroborations: 1
---

# Escape ledger two-stage collapse: by id, then by detection_ref

When collapsing `escape_ledger.jsonl` rows, collapse in two passes: first by `id` (latest-appended wins, per existing `append_resolution` semantics), then by `detection_ref` — an `encoded_as != "none-yet"` row always wins over a bare detector row; otherwise pick strongest confidence (high>medium>low), tie-broken by latest. This lives in `src/escape/metrics.py::latest_by_escape`, consumed by `src/escape/ledger.py::read_latest()`.

**Why:** collapsing by `detection_ref` alone would let a later `none-yet` detector rerun silently discard a human `append_resolution` row for the same commit — the encoded-wins rule plus a counter-pin test guards against that.
