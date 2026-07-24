---
id: 0415
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:02:15.953148+00:00
status: active
corroborations: 1
supersedes: 0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401
---

# Ledger refactors must preserve byte-identical JSONL output

When consolidating store implementations (e.g. `src/escape/ledger.py`, `src/erosion/trends.py`) into a shared base like `src/jsonl_ledger.py`, explicitly test that JSON encoding options, the trailing newline, and malformed-line-skip behavior on `read_all` are unchanged. Example: assert historical `.jsonl` files on disk still parse the same way after the refactor. See also: patterns — JSONL ledger stores share a generic base in src/jsonl_ledger.py. **Why:** these stores are append-only logs read by existing pipeline data; a silent encoding or newline change breaks readers of already-written files.
