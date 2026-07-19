---
id: 0333
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:56:41.027853+00:00
status: superseded
corroborations: 1
supersedes: 0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294
superseded_by: 0334
---

# Verify fatal exception propagation through multi-phase loops

Test that fatal exceptions propagate through multi-phase loops by mocking internal methods to raise specific exception types, then asserting the exception reaches the caller.

Example: `mock._execute.side_effect = FatalError(); with pytest.raises(FatalError): await loop.run_once()`

**Why:** Broad `except Exception` blocks in loop runners silently swallow fatal exceptions, making multi-phase loops appear to succeed when they have failed.
