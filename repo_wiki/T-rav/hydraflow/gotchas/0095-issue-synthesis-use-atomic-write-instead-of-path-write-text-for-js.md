---
id: 0095
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:46:56.518627+00:00
status: active
corroborations: 1
supersedes: 0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077
---

# Use `atomic_write()` instead of `Path.write_text()` for JSON state

Write JSON state files via `file_util.atomic_write()`, not `Path.write_text()`.

Example: `atomic_write(state_path, json_str)` writes to a `.tmp` sibling then renames atomically — a crash mid-write leaves the original intact.

**Why:** `Path.write_text()` truncates before writing; a crash mid-operation produces a zero-byte or partial JSON that fails to parse on restart, corrupting persisted state.
