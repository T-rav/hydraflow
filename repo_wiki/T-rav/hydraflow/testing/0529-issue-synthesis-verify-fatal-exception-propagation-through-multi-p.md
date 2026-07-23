---
id: 0529
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T13:39:13.371046+00:00
status: superseded
corroborations: 1
supersedes: 0510,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519
superseded_by: 0531
---

# Verify fatal exception propagation through multi-phase loops

Test that fatal exceptions propagate through multi-phase loops (ADR-0001) by mocking internal methods to raise specific exception types, then asserting the exception reaches the caller.

Example: `mock._execute.side_effect = FatalError(); with pytest.raises(FatalError): await loop.run_once()`. See also: architecture-async-control.md — error hierarchy.

**Why:** Broad `except Exception` blocks in loop runners silently swallow fatal exceptions, making multi-phase loops appear to succeed when they have failed.
