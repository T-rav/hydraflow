---
id: 0206
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:22:06.638570+00:00
status: superseded
corroborations: 1
supersedes: 0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175
superseded_by: 0218
---

# Use SHA-256 truncated to 16 chars for memory dedup keys

Compute dedup keys and recall-hit tracking via `SHA-256(content)[:16]`.

Example: `key = hashlib.sha256(item['text'].encode()).hexdigest()[:16]`.

**Why:** Consistent hashing ensures the same content maps to the same key across process restarts; truncation keeps keys human-scannable in logs.
