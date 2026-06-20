---
id: 0038
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.318976+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Use SHA-256 truncated to 16 chars for memory dedup keys

Compute dedup keys and recall-hit tracking via `SHA-256(content)[:16]`.

Example: `key = hashlib.sha256(item['text'].encode()).hexdigest()[:16]`.

**Why:** Consistent hashing ensures the same content maps to the same key across process restarts; truncation keeps keys human-scannable in logs.
