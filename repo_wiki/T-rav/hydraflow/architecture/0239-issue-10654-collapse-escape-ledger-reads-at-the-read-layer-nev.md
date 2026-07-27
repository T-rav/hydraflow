---
id: 0239
topic: architecture
source_issue: 10654
source_phase: plan
created_at: 2026-07-26T16:24:44.376063+00:00
status: active
corroborations: 1
---

# Collapse escape-ledger reads at the read layer, never rewrite JSONL

When a commit is re-detected under a stronger source, the append-only ledger holds both rows. Fix derived reads by collapsing in `escape/metrics.py::latest_by_escape`, not by rewriting or deleting raw lines.

- `EscapeLedger.read_latest()` delegates to `latest_by_escape`, which runs `latest_by_id` first (preserving `append_resolution` chains), then groups by `detection_ref`.
- The JSONL on disk keeps every raw line — the collapse is a read-time view.

**Why:** The ledger is an audit trail; #10561 failed because it tried a self-heal/git-adapter rewrite. Read-layer collapse converges without violating append-only.
