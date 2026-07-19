---
id: 0129
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:54:44.602663+00:00
status: superseded
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
superseded_by: 0146
---

# Use `atomic_write()` instead of `Path.write_text()` for JSON state

Write JSON state files via `file_util.atomic_write()`, not `Path.write_text()`.

Example: `atomic_write(state_path, json_str)` writes to a `.tmp` sibling then renames atomically — a crash mid-write leaves the original intact.

**Why:** `Path.write_text()` truncates before writing; a crash mid-operation produces a zero-byte or partial JSON that fails to parse on restart, corrupting persisted state.
