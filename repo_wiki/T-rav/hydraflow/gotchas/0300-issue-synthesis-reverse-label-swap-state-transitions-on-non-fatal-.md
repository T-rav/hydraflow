---
id: 0300
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T08:12:52.210818+00:00
status: active
corroborations: 1
supersedes: 0288,0289,0290,0291,0292,0293
---

# Reverse label-swap state transitions on non-fatal exceptions

Wrap label-swap + operation + cleanup in try/except and reverse the transition on non-fatal errors, per the ADR-0002 labels-as-state-machine model.

Example: if a label is swapped `plan → implement` but the follow-up API call fails, swap it back to `plan` before re-raising.

**Why:** An exception after a successful state transition but before cleanup leaves issues stuck in intermediate label states with no automated recovery path.
