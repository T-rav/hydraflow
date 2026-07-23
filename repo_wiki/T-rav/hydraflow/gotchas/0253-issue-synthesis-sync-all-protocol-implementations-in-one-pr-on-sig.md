---
id: 0253
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:39:19.017872+00:00
status: superseded
corroborations: 1
supersedes: 0214,0215,0216,0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247
superseded_by: 0282
---

# Sync all protocol implementations in one PR on signature change

When a port or protocol method signature changes, update every concrete implementation atomically in the same PR — never staggered across tasks.

Example: adding `ctx: Context` to `def process(self, item)` requires changing every class implementing the protocol before merging.

**Why:** Staggered updates leave implementations out of sync with the protocol, causing Pyright errors that block CI until every site is updated.
