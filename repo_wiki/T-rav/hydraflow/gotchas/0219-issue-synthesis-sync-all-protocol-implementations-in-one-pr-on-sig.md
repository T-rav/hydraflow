---
id: 0219
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:45:05.794093+00:00
status: superseded
corroborations: 1
supersedes: 0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213
superseded_by: 0248
---

# Sync all protocol implementations in one PR on signature change

When a port or protocol method signature changes, update every concrete implementation atomically in the same PR — never staggered across tasks.

Example: adding `ctx: Context` to `def process(self, item)` requires changing every class implementing the protocol before merging.

**Why:** Staggered updates leave implementations out of sync with the protocol, causing Pyright errors that block CI until every site is updated.
