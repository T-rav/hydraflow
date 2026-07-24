---
id: 0445
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:06:34.707459+00:00
status: superseded
corroborations: 1
supersedes: 0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431
superseded_by: 0447
---

# Ledger refactors must preserve byte-identical JSONL output

When consolidating store implementations (e.g. `src/escape/ledger.py`, `src/erosion/trends.py`) into a shared base like `src/jsonl_ledger.py`, explicitly test that JSON encoding options, the trailing newline, and malformed-line-skip behavior on `read_all` are unchanged. Example: assert historical `.jsonl` files on disk still parse the same way after the refactor. See also: patterns — JSONL ledger stores share a generic base in src/jsonl_ledger.py. **Why:** these stores are append-only logs read by existing pipeline data; a silent encoding or newline change breaks readers of already-written files.
