---
id: 0377
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:12:12.384720+00:00
status: active
corroborations: 1
supersedes: 0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369
---

# Reverse label-swap state transitions on non-fatal exceptions

Wrap label-swap + operation + cleanup in try/except and reverse the transition on non-fatal errors, per the ADR-0002 labels-as-state-machine model.

Example: if a label is swapped `plan → implement` but the follow-up API call fails, swap it back to `plan` before re-raising.

**Why:** An exception after a successful state transition but before cleanup leaves issues stuck in intermediate label states with no automated recovery path.
