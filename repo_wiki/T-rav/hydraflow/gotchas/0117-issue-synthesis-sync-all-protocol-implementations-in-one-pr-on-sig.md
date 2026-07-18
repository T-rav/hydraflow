---
id: 0117
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:37:07.464595+00:00
status: active
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
---

# Sync all protocol implementations in one PR on signature change

When a port or protocol method signature changes, update every concrete implementation atomically in the same PR — never staggered across tasks.

Example: adding `ctx: Context` to `def process(self, item)` requires changing every class implementing the protocol before merging.

**Why:** Staggered updates leave implementations out of sync with the protocol, causing Pyright errors that block CI until every site is updated.
