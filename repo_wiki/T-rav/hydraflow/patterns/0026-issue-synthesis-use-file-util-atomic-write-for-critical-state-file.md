---
id: 0026
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.316464+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Use `file_util.atomic_write()` for critical state file updates

Write critical state via `file_util.atomic_write()`, which writes to a temp file then calls `os.replace()` atomically.

Example: `file_util.atomic_write(state_path, json.dumps(state))` — not `open(path, 'w').write(...)`.

**Why:** A crash mid-write with `open(..., 'w')` truncates the file, producing an empty or partial state that cannot be loaded.
