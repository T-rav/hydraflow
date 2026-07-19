---
id: 0248
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:45:28.228500+00:00
status: superseded
corroborations: 1
supersedes: 0176,0177,0178,0179,0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213,0214,0215,0216,0217
superseded_by: 0260
---

# Use SHA-256 truncated to 16 chars for memory dedup keys

Compute dedup keys and recall-hit tracking via `SHA-256(content)[:16]`.

Example: `key = hashlib.sha256(item['text'].encode()).hexdigest()[:16]`.

**Why:** Consistent hashing ensures the same content maps to the same key across process restarts; truncation keeps keys human-scannable in logs.
