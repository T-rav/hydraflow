---
id: 0401
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:23:13.613214+00:00
status: superseded
corroborations: 1
supersedes: 0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387
superseded_by: 0402
---

# Ledger refactors must preserve byte-identical JSONL output

When consolidating store implementations (e.g. `src/escape/ledger.py`, `src/erosion/trends.py`) into a shared base like `src/jsonl_ledger.py` (see also: patterns — JSONL ledger stores share a generic base), explicitly test that JSON encoding options, the trailing newline, and malformed-line-skip behavior on `read_all` are unchanged.

Example: assert historical `.jsonl` files on disk still parse the same way after the refactor.

**Why:** these stores are append-only logs read by existing pipeline data; a silent encoding or newline change breaks readers of already-written files.
