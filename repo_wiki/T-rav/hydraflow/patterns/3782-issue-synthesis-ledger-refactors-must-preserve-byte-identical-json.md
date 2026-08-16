---
id: 3782
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T15:30:55.707409+00:00
status: active
corroborations: 1
supersedes: 3637
---

# Ledger refactors must preserve byte-identical JSONL output

When consolidating store implementations into a shared base like `src/jsonl_ledger.py`, explicitly test that JSON encoding options, trailing newline, and malformed-line-skip behavior on `read_all` are unchanged.

Example: Assert historical `.jsonl` files on disk still parse the same way after the refactor. See also: [patterns] — JSONL ledger stores share a generic base in src/jsonl_ledger.py.

**Why:** These stores are append-only logs read by existing pipeline data; a silent encoding or newline change breaks readers of already-written files.
