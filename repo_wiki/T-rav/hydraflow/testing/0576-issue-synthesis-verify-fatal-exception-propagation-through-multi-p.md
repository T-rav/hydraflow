---
id: 0576
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:13:41.427450+00:00
status: active
corroborations: 1
supersedes: 0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566
---

# Verify fatal exception propagation through multi-phase loops

Test that fatal exceptions propagate through multi-phase loops (ADR-0001) by mocking internal methods to raise specific exception types, then asserting the exception reaches the caller.

Example: `mock._execute.side_effect = FatalError(); with pytest.raises(FatalError): await loop.run_once()`. See also: architecture-async-control.md — error hierarchy.

**Why:** Broad `except Exception` blocks in loop runners silently swallow fatal exceptions, making multi-phase loops appear to succeed when they have failed.
