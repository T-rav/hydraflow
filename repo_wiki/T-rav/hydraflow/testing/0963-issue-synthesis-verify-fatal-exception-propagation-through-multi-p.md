---
id: 0963
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.550841+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
---

# Verify fatal exception propagation through multi-phase loops

Test that fatal exceptions propagate through multi-phase loops (ADR-0001) by mocking internal methods to raise specific exception types, then asserting the exception reaches the caller.

Example: mock._execute.side_effect = FatalError(); with pytest.raises(FatalError): await loop.run_once(). See also: architecture-async-control.md — error hierarchy.

**Why:** Broad except Exception blocks in loop runners silently swallow fatal exceptions, making multi-phase loops appear to succeed when they have failed.
