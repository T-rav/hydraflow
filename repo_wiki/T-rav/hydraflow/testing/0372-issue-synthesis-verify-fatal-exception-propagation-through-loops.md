---
id: 0372
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:25:25.509324+00:00
status: superseded
corroborations: 1
supersedes: 0295,0296,0297,0298,0299,0300,0301,0302,0303,0304,0305,0306,0307,0308,0309,0310,0311,0312,0313,0314,0315,0316,0317,0318,0319,0320,0321,0322,0323,0324,0325,0326,0327,0328,0329,0330,0331,0332,0333
superseded_by: 0373
---

# Verify fatal exception propagation through loops

Test that fatal exceptions propagate through multi-phase loops by mocking internal methods to raise specific exception types, then asserting the exception reaches the caller.

Example: `mock._execute.side_effect = FatalError(); with pytest.raises(FatalError): await loop.run_once()`

**Why:** Broad `except Exception` blocks in loop runners silently swallow fatal exceptions, making multi-phase loops appear to succeed when they have failed.
