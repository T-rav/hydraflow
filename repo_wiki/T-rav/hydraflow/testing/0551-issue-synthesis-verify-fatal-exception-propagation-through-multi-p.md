---
id: 0551
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T17:03:32.126050+00:00
status: superseded
corroborations: 1
supersedes: 0531,0532,0533,0534,0535,0536,0537,0538,0539,0540,0541
superseded_by: 0553
---

# Verify fatal exception propagation through multi-phase loops

Test that fatal exceptions propagate through multi-phase loops (ADR-0001) by mocking internal methods to raise specific exception types, then asserting the exception reaches the caller.

Example: `mock._execute.side_effect = FatalError(); with pytest.raises(FatalError): await loop.run_once()`. See also: architecture-async-control.md — error hierarchy.

**Why:** Broad `except Exception` blocks in loop runners silently swallow fatal exceptions, making multi-phase loops appear to succeed when they have failed.
