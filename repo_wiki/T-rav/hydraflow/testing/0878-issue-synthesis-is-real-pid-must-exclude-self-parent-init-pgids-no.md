---
id: 0878
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:22:24.536714+00:00
status: superseded
corroborations: 1
supersedes: 0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0825,0826,0827,0828,0829,0830,0831,0832,0833,0834,0835,0836,0837,0838,0839,0840,0841,0842,0843,0844,0845,0846
superseded_by: 0898
---

# is_real_pid must exclude self/parent/init pgids, not just bool/0/negative

Exclude self/parent/init pgids in `is_real_pid` (`src/process_group.py`), not just `bool`, `0`, and negative values — extend the exclusion set to `{1, os.getpid(), os.getppid(), os.getpgrp()}`.

Example: without this, a fake `.pid` matching init (`1`), the test process, or its parent reaches `os.killpg` on the reaper's own process group, SIGKILLing the pytest run mid-suite on Linux (macOS masks it as a benign `EPERM`, so local runs pass while CI's `Coverage (trailing)` job gets CANCELLED with zero FAILED lines).

**Why:** platform-divergent signal semantics (EPERM on macOS vs success on Linux) hide this class of bug from local dev entirely — it only surfaces in CI.
