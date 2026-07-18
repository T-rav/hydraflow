---
id: 0109
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T18:31:58.101899+00:00
status: active
corroborations: 1
supersedes: 0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091
---

# Use `file_util.append_jsonl()` for crash-safe JSONL appends

Wrap JSONL appends in `file_util.append_jsonl()`, which calls `flush()` + `os.fsync()` inside a `file_lock()`.

Example: `file_util.append_jsonl(path, record)` — not `with open(path, 'a') as f: f.write(...)`.

**Why:** Bare `open(..., 'a')` without fsync loses the last record on crash; the lock prevents interleaved writes from concurrent processes.
