---
id: 0596
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:08:06.340257+00:00
status: active
corroborations: 1
supersedes: 0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583
---

# Ledger refactors must preserve byte-identical JSONL output

When consolidating store implementations into a shared base like `src/jsonl_ledger.py`, explicitly test that JSON encoding options, trailing newlines, and malformed-line-skip behavior on `read_all` are unchanged.

Example: assert historical `.jsonl` files on disk still parse the same way after the refactor. See also: patterns — JSONL ledger stores share a generic base.

**Why:** these stores are append-only logs read by existing pipeline data; a silent encoding or newline change breaks readers.
