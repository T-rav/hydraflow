---
id: 0624
topic: testing
source_issue: 10393
source_phase: plan
created_at: 2026-07-24T04:45:18.081887+00:00
status: active
corroborations: 1
---

# is_real_pid must exclude self/parent/init pgids, not just bool/0/negative

`is_real_pid` in `src/process_group.py` originally only rejected `bool`, `0`, and negative values — it admitted `1` (init), `os.getpid()`, and `os.getppid()`. A fake `.pid` matching one of those reaches `os.killpg` on the reaper's own process group, SIGKILLing the pytest run mid-suite on Linux (macOS masks it as a benign `EPERM`, so local runs pass while CI's `Coverage (trailing)` job gets CANCELLED with zero FAILED lines).

Extend the exclusion set to `{1, os.getpid(), os.getppid(), os.getpgrp()}` in addition to the existing checks.

**Why:** platform-divergent signal semantics (EPERM on macOS vs success on Linux) hide this class of bug from local dev entirely — it only surfaces in CI.
