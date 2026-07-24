---
id: 0829
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:43:21.206723+00:00
status: superseded
corroborations: 1
supersedes: 0754,0755,0756,0757,0758,0759,0760,0761,0762,0763,0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797
superseded_by: 0847
---

# is_real_pid must exclude self/parent/init pgids, not just bool/0/negative

Exclude self/parent/init pgids in `is_real_pid` (`src/process_group.py`), not just `bool`, `0`, and negative values — extend the exclusion set to `{1, os.getpid(), os.getppid(), os.getpgrp()}`.

Example: without this, a fake `.pid` matching init (`1`), the test process, or its parent reaches `os.killpg` on the reaper's own process group, SIGKILLing the pytest run mid-suite on Linux (macOS masks it as a benign `EPERM`, so local runs pass while CI's `Coverage (trailing)` job gets CANCELLED with zero FAILED lines).

**Why:** platform-divergent signal semantics (EPERM on macOS vs success on Linux) hide this class of bug from local dev entirely — it only surfaces in CI.
