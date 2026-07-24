---
id: 0429
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:37:01.328079+00:00
status: superseded
corroborations: 1
supersedes: 0402,0403,0404,0405,0406,0407,0408,0409,0410,0411,0412,0413,0414,0415
superseded_by: 0432
---

# Ledger refactors must preserve byte-identical JSONL output

When consolidating store implementations (e.g. `src/escape/ledger.py`, `src/erosion/trends.py`) into a shared base like `src/jsonl_ledger.py`, explicitly test that JSON encoding options, the trailing newline, and malformed-line-skip behavior on `read_all` are unchanged. Example: assert historical `.jsonl` files on disk still parse the same way after the refactor. See also: patterns — JSONL ledger stores share a generic base in src/jsonl_ledger.py. **Why:** these stores are append-only logs read by existing pipeline data; a silent encoding or newline change breaks readers of already-written files.
