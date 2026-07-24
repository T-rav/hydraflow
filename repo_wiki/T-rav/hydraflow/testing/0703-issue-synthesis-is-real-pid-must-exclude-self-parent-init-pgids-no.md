---
id: 0703
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.879560+00:00
status: active
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
---

# is_real_pid must exclude self/parent/init pgids, not just bool/0/negative

Exclude self/parent/init pgids in `is_real_pid` (`src/process_group.py`), not just `bool`, `0`, and negative values — extend the exclusion set to `{1, os.getpid(), os.getppid(), os.getpgrp()}`.

Example: without this, a fake `.pid` matching init (`1`), the test process, or its parent reaches `os.killpg` on the reaper's own process group, SIGKILLing the pytest run mid-suite on Linux (macOS masks it as a benign `EPERM`, so local runs pass while CI's `Coverage (trailing)` job gets CANCELLED with zero FAILED lines).

**Why:** platform-divergent signal semantics (EPERM on macOS vs success on Linux) hide this class of bug from local dev entirely — it only surfaces in CI.
