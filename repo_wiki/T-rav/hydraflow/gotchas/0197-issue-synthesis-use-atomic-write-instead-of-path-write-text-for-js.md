---
id: 0197
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:47:09.156311+00:00
status: active
corroborations: 1
supersedes: 0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179
---

# Use `atomic_write()` instead of `Path.write_text()` for JSON state

Write JSON state files via `file_util.atomic_write()`, not `Path.write_text()`.

Example: `atomic_write(state_path, json_str)` writes to a `.tmp` sibling then renames atomically — a crash mid-write leaves the original intact.

**Why:** `Path.write_text()` truncates before writing; a crash mid-operation produces a zero-byte or partial JSON that fails to parse on restart, corrupting persisted state.
