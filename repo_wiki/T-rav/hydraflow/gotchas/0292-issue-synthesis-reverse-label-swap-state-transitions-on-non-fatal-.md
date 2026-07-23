---
id: 0292
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T06:25:49.699295+00:00
status: superseded
corroborations: 1
supersedes: 0282,0283,0284,0285,0286,0287
superseded_by: 0296
---

# Reverse label-swap state transitions on non-fatal exceptions

Rule: Wrap label-swap + operation + cleanup in try/except and reverse the transition on non-fatal errors, per the ADR-0002 labels-as-state-machine model.

Example: if a label is swapped `plan → implement` but the follow-up API call fails, swap it back to `plan` before re-raising.

**Why:** An exception after a successful state transition but before cleanup leaves issues stuck in intermediate label states with no automated recovery path.
