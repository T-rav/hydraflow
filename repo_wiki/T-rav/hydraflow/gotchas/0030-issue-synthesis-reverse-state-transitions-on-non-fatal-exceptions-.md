---
id: 0030
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.696297+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# Reverse state transitions on non-fatal exceptions to avoid stuck issues

Wrap label-swap + operation + cleanup in a try/except that reverses the transition on non-fatal errors.

Example: if a label is swapped `plan → implement` but the API call fails, swap it back to `plan` before re-raising.

**Why:** An exception after a successful state transition but before cleanup leaves issues stuck in intermediate states with no automated recovery path.
