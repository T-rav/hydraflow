---
id: 0277
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:42:57.714380+00:00
status: superseded
corroborations: 1
supersedes: 0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255,0256,0257,0258,0259
superseded_by: 0302
---

# Use `file_util.append_jsonl()` for crash-safe JSONL appends

Wrap JSONL appends in `file_util.append_jsonl()`, which calls `flush()` + `os.fsync()` inside a `file_lock()`.

Example: `file_util.append_jsonl(path, record)` — not `with open(path, 'a') as f: f.write(...)`.

**Why:** Bare `open(..., 'a')` without fsync loses the last record on crash; the lock prevents interleaved writes from concurrent processes.
