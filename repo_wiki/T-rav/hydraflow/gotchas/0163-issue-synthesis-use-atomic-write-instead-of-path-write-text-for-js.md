---
id: 0163
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:23:52.952620+00:00
status: superseded
corroborations: 1
supersedes: 0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145
superseded_by: 0180
---

# Use `atomic_write()` instead of `Path.write_text()` for JSON state

Write JSON state files via `file_util.atomic_write()`, not `Path.write_text()`.

Example: `atomic_write(state_path, json_str)` writes to a `.tmp` sibling then renames atomically — a crash mid-write leaves the original intact.

**Why:** `Path.write_text()` truncates before writing; a crash mid-operation produces a zero-byte or partial JSON that fails to parse on restart, corrupting persisted state.
