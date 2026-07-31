---
id: 1965
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:50:52.837183+00:00
status: active
corroborations: 1
supersedes: 1838
---

# Verify fatal exception propagation through multi-phase loops

Test that fatal exceptions propagate through multi-phase loops (ADR-0001) by mocking internal methods to raise specific exception types, then asserting the exception reaches the caller.

Example: `mock._execute.side_effect = FatalError(); with pytest.raises(FatalError): await loop.run_once()`. See also: architecture — error hierarchy.

**Why:** Broad `except Exception` blocks in loop runners silently swallow fatal exceptions, making multi-phase loops appear to succeed when they have failed.
