---
id: 0324
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T13:38:34.196736+00:00
status: superseded
corroborations: 1
supersedes: 0310,0310,0311,0311,0312,0312,0313,0314,0315,0316
superseded_by: 0327
---

# Reverse label-swap state transitions on non-fatal exceptions

Wrap label-swap + operation + cleanup in try/except and reverse the transition on non-fatal errors, per the ADR-0002 labels-as-state-machine model.

Example: if a label is swapped `plan → implement` but the follow-up API call fails, swap it back to `plan` before re-raising.

**Why:** An exception after a successful state transition but before cleanup leaves issues stuck in intermediate label states with no automated recovery path.
