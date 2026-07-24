---
id: 0409
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:55:43.287363+00:00
status: active
corroborations: 1
supersedes: 0370,0371,0372,0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387,0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401
---

# Reverse label-swap state transitions on non-fatal exceptions

Wrap label-swap + operation + cleanup in try/except and reverse the transition on non-fatal errors, per the ADR-0002 labels-as-state-machine model.

Example: if a label is swapped `plan → implement` but the follow-up API call fails, swap it back to `plan` before re-raising.

**Why:** An exception after a successful state transition but before cleanup leaves issues stuck in intermediate label states with no automated recovery path.
