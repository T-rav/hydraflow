---
id: 0025
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.316252+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Use `file_util.append_jsonl()` for crash-safe JSONL appends

Wrap JSONL appends in `file_util.append_jsonl()`, which calls `flush()` + `os.fsync()` inside a `file_lock()`.

Example: `file_util.append_jsonl(path, record)` — not `with open(path, 'a') as f: f.write(...)`.

**Why:** Bare `open(..., 'a')` without fsync loses the last record on crash; the lock prevents interleaved writes from concurrent processes.
