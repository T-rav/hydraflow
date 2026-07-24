---
id: 0476
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T15:40:09.615155+00:00
status: active
corroborations: 1
supersedes: 0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462
---

# Ledger refactors must preserve byte-identical JSONL output

When consolidating store implementations (e.g. `src/escape/ledger.py`, `src/erosion/trends.py`) into a shared base like `src/jsonl_ledger.py`, explicitly test that JSON encoding options, the trailing newline, and malformed-line-skip behavior on `read_all` are unchanged.

Example: assert historical `.jsonl` files on disk still parse the same way after the refactor. See also: patterns — JSONL ledger stores share a generic base in src/jsonl_ledger.py.

**Why:** these stores are append-only logs read by existing pipeline data; a silent encoding or newline change breaks readers of already-written files.
