---
id: 0852
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T19:37:32.620410+00:00
status: superseded
corroborations: 1
supersedes: 0797
superseded_by: 0910
---

# Ledger refactors must preserve byte-identical JSONL output

When consolidating store implementations into a shared base like `src/jsonl_ledger.py`, explicitly test that JSON encoding options, trailing newline, and malformed-line-skip behavior on `read_all` are unchanged.

Example: Assert historical `.jsonl` files on disk still parse the same way after the refactor. See also: patterns — JSONL ledger stores share a generic base in src/jsonl_ledger.py.

**Why:** These stores are append-only logs read by existing pipeline data; a silent encoding or newline change breaks readers of already-written files.
