---
id: 0151
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:52:49.025870+00:00
status: active
corroborations: 1
supersedes: 0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133
---

# Use `file_util.append_jsonl()` for crash-safe JSONL appends

Wrap JSONL appends in `file_util.append_jsonl()`, which calls `flush()` + `os.fsync()` inside a `file_lock()`.

Example: `file_util.append_jsonl(path, record)` — not `with open(path, 'a') as f: f.write(...)`.

**Why:** Bare `open(..., 'a')` without fsync loses the last record on crash; the lock prevents interleaved writes from concurrent processes.
