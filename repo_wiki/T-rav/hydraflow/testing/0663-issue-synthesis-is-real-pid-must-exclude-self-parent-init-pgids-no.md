---
id: 0663
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:31:08.508777+00:00
status: superseded
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631
superseded_by: 0672
---

# is_real_pid must exclude self/parent/init pgids, not just bool/0/negative

`is_real_pid` in `src/process_group.py` originally only rejected `bool`, `0`, and negative values — it admitted `1` (init), `os.getpid()`, and `os.getppid()`. A fake `.pid` matching one of those reaches `os.killpg` on the reaper's own process group, SIGKILLing the pytest run mid-suite on Linux (macOS masks it as a benign `EPERM`, so local runs pass while CI's `Coverage (trailing)` job gets CANCELLED with zero FAILED lines).

Example: extend the exclusion set to `{1, os.getpid(), os.getppid(), os.getpgrp()}` in addition to the existing checks.

**Why:** platform-divergent signal semantics (EPERM on macOS vs success on Linux) hide this class of bug from local dev entirely — it only surfaces in CI.
