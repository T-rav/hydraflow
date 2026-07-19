---
id: 0132
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:54:44.603703+00:00
status: superseded
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
superseded_by: 0146
---

# Reverse state transitions on non-fatal exceptions to avoid stuck

Wrap label-swap + operation + cleanup in a try/except that reverses the transition on non-fatal errors.

Example: if a label is swapped `plan → implement` but the API call fails, swap it back to `plan` before re-raising.

**Why:** An exception after a successful state transition but before cleanup leaves issues stuck in intermediate states with no automated recovery path.
