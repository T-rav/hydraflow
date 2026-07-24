---
id: 0386
topic: patterns
source_issue: 10403
source_phase: plan
created_at: 2026-07-24T05:36:17.563792+00:00
status: superseded
corroborations: 1
superseded_by: 0388
---

# Ledger refactors must preserve byte-identical JSONL output

When consolidating store implementations (e.g. `src/escape/ledger.py`, `src/erosion/trends.py`) into a shared base, explicitly test that JSON encoding options, the trailing newline, and malformed-line-skip behavior on `read_all` are unchanged — historical `.jsonl` files on disk must still parse the same way after the refactor.

**Why:** these stores are append-only logs read by existing pipeline data; a silent encoding or newline change breaks readers of already-written files.
