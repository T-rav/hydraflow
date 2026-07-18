---
id: 0164
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:34:46.628647+00:00
status: active
corroborations: 1
supersedes: 0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133
---

# Use SHA-256 truncated to 16 chars for memory dedup keys

Compute dedup keys and recall-hit tracking via `SHA-256(content)[:16]`.

Example: `key = hashlib.sha256(item['text'].encode()).hexdigest()[:16]`.

**Why:** Consistent hashing ensures the same content maps to the same key across process restarts; truncation keeps keys human-scannable in logs.
