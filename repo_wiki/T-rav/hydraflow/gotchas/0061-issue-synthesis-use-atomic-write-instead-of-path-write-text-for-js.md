---
id: 0061
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T04:11:59.907384+00:00
status: active
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
---

# Use `atomic_write()` instead of `Path.write_text()` for JSON state files

Write JSON state files via `file_util.atomic_write()`, not `Path.write_text()`.

Example: `atomic_write(state_path, json_str)` writes to a `.tmp` sibling then renames atomically — a crash mid-write leaves the original intact.

**Why:** `Path.write_text()` truncates before writing; a crash mid-operation produces a zero-byte or partial JSON that fails to parse on restart, corrupting persisted state.
