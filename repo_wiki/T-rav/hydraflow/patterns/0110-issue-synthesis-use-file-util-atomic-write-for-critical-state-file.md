---
id: 0110
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:45:43.962220+00:00
status: active
corroborations: 1
supersedes: 0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091
---

# Use `file_util.atomic_write()` for critical state file updates

Write critical state via `file_util.atomic_write()`, which writes to a temp file then calls `os.replace()` atomically.

Example: `file_util.atomic_write(state_path, json.dumps(state))` — not `open(path, 'w').write(...)`.

**Why:** A crash mid-write with `open(..., 'w')` truncates the file, producing an empty or partial state that cannot be loaded.
