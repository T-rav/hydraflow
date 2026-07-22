---
id: 0344
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T17:02:49.507763+00:00
status: active
corroborations: 1
supersedes: 0327,0328,0329,0330,0331,0332,0333,0334,0335,0336
---

# Reverse label-swap state transitions on non-fatal exceptions

Wrap label-swap + operation + cleanup in try/except and reverse the transition on non-fatal errors, per the ADR-0002 labels-as-state-machine model.

Example: if a label is swapped `plan → implement` but the follow-up API call fails, swap it back to `plan` before re-raising.

**Why:** An exception after a successful state transition but before cleanup leaves issues stuck in intermediate label states with no automated recovery path.
