---
id: 0151
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:23:52.948967+00:00
status: superseded
corroborations: 1
supersedes: 0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145
superseded_by: 0180
---

# Sync all protocol implementations in one PR on signature change

When a port or protocol method signature changes, update every concrete implementation atomically in the same PR — never staggered across tasks.

Example: adding `ctx: Context` to `def process(self, item)` requires changing every class implementing the protocol before merging.

**Why:** Staggered updates leave implementations out of sync with the protocol, causing Pyright errors that block CI until every site is updated.
