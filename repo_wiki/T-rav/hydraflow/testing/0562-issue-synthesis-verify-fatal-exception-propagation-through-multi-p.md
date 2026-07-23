---
id: 0562
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T18:03:23.962400+00:00
status: active
corroborations: 1
supersedes: 0542,0543,0544,0545,0546,0547,0548,0549,0550,0551,0552
---

# Verify fatal exception propagation through multi-phase loops

Test that fatal exceptions propagate through multi-phase loops (ADR-0001) by mocking internal methods to raise specific exception types, then asserting the exception reaches the caller.

Example: `mock._execute.side_effect = FatalError(); with pytest.raises(FatalError): await loop.run_once()`. See also: architecture-async-control.md — error hierarchy.

**Why:** Broad `except Exception` blocks in loop runners silently swallow fatal exceptions, making multi-phase loops appear to succeed when they have failed.
