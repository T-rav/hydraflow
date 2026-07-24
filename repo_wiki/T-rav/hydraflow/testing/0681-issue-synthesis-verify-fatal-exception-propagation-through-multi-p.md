---
id: 0681
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.844232+00:00
status: active
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
---

# Verify fatal exception propagation through multi-phase loops

Test that fatal exceptions propagate through multi-phase loops (ADR-0001) by mocking internal methods to raise specific exception types, then asserting the exception reaches the caller.

Example: `mock._execute.side_effect = FatalError(); with pytest.raises(FatalError): await loop.run_once()`. See also: architecture-async-control.md — error hierarchy.

**Why:** Broad `except Exception` blocks in loop runners silently swallow fatal exceptions, making multi-phase loops appear to succeed when they have failed.
