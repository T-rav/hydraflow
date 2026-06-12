---
id: 0012
topic: gotchas
source_issue: 9441
source_phase: review
created_at: 2026-06-12T13:54:23.578705+00:00
status: active
corroborations: 1
---

# _ORCHESTRATOR_DRIVEN_LOOPS constant AND routing branch both required

`tests/scenarios/test_sandbox_parity.py` gates orchestrator-driven loops via `_ORCHESTRATOR_DRIVEN_LOOPS`. Adding a new orchestrator-driven loop requires **both**:

1. Loop name added to the constant
2. Corresponding routing branch that handles the orchestrator-driven path

A missing constant entry silently routes through the default path and produces a wrong result instead of a clean failure.

**Why:** Half-wired state hides the gap — the test appears to pass on the wrong branch rather than raising a routing error.
