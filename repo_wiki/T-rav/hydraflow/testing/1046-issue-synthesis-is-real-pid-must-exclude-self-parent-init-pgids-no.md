---
id: 1046
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.504708+00:00
status: active
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
---

# is_real_pid must exclude self/parent/init pgids, not just bool/0/negative

Exclude self/parent/init pgids in is_real_pid (src/process_group.py), not just bool, 0, and negative values — extend the exclusion set to {1, os.getpid(), os.getppid(), os.getpgrp()}.

Example: without this, a fake .pid matching init (1), the test process, or its parent reaches os.killpg on the reaper's own process group, SIGKILLing the pytest run mid-suite on Linux (macOS masks it as a benign EPERM, so local runs pass while CI's Coverage job gets CANCELLED with zero FAILED lines).

**Why:** platform-divergent signal semantics (EPERM on macOS vs success on Linux) hide this class of bug from local dev entirely — it only surfaces in CI.
