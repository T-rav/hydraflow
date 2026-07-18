---
id: 0080
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T14:57:29.439989+00:00
status: active
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
---

# Use SHA-256 truncated to 16 chars for memory dedup keys

Compute dedup keys and recall-hit tracking via `SHA-256(content)[:16]`.

Example: `key = hashlib.sha256(item['text'].encode()).hexdigest()[:16]`.

**Why:** Consistent hashing ensures the same content maps to the same key across process restarts; truncation keeps keys human-scannable in logs.
