---
id: 0985
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.577838+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
---

# is_real_pid must exclude self/parent/init pgids, not just bool/0/negative

Exclude self/parent/init pgids in is_real_pid (src/process_group.py), not just bool, 0, and negative values — extend the exclusion set to {1, os.getpid(), os.getppid(), os.getpgrp()}.

Example: without this, a fake .pid matching init (1), the test process, or its parent reaches os.killpg on the reaper's own process group, SIGKILLing the pytest run mid-suite on Linux (macOS masks it as a benign EPERM, so local runs pass while CI's Coverage (trailing) job gets CANCELLED with zero FAILED lines).

**Why:** platform-divergent signal semantics (EPERM on macOS vs success on Linux) hide this class of bug from local dev entirely — it only surfaces in CI.
