---
id: 0015
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.693526+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# Sync all protocol implementations in one PR when a port signature changes

When a port or protocol method signature changes, update every concrete implementation atomically in the same PR — never staggered across tasks.

Example: adding `ctx: Context` to `def process(self, item)` requires changing every class implementing the protocol before merging.

**Why:** Staggered updates leave implementations out of sync with the protocol, causing Pyright errors that block CI until every site is updated.
