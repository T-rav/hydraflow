---
id: 0018
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.314799+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Extract duplicated JSONL-reading logic to a shared `_load_jsonl()` helper

Shared JSONL-reading logic must be extracted to a `_load_jsonl(path, label)` helper rather than duplicated inline.

Example: `records = _load_jsonl(path, "events")` — one implementation, multiple callers.

**Why:** Inline duplication causes silent divergence when one copy gets a bug fix (e.g., empty-file guard) that the other copies miss.
