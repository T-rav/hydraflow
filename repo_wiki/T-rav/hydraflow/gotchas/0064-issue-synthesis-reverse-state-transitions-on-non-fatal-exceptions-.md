---
id: 0064
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:16:33.338029+00:00
status: active
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
---

# Reverse state transitions on non-fatal exceptions to avoid stuck

Wrap label-swap + operation + cleanup in a try/except that reverses the transition on non-fatal errors.

Example: if a label is swapped `plan → implement` but the API call fails, swap it back to `plan` before re-raising.

**Why:** An exception after a successful state transition but before cleanup leaves issues stuck in intermediate states with no automated recovery path.
