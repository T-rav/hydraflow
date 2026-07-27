---
id: 0906
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:15:44.759732+00:00
status: superseded
corroborations: 1
supersedes: 0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797,0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0826,0827,0828,0829,0830,0833,0834,0838,0839,0840,0841,0842,0843,0844,0848,0848,0848,0849,0850
superseded_by: 0940
---

# Attempt counters bump-before-run means max-attempt is always unprotected

Both `get_issue_attempts` and `get_auto_agent_attempts` in this repo are incremented *before* the run starts and cleared on close/success. A retry-window guard written as `0 < attempts < max_attempts` therefore never protects the final attempt (`attempts == max`), since that run is in-flight but the bound excludes it.

Example: this is an accepted, theoretical residual race in `src/workspace_gc_loop.py` — not a regression to fix inline; closing it fully requires a live session lock/heartbeat, tracked as a `hydraflow-find` follow-up rather than blocking the fix.

**Why:** documents why the last-attempt gap is intentional scope-out, so future readers don't re-flag it as an unfixed bug.
