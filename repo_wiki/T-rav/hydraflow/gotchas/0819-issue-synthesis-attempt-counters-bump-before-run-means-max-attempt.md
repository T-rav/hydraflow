---
id: 0819
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:43:04.021040+00:00
status: superseded
corroborations: 1
supersedes: 0704,0705,0706,0707,0708,0709,0710,0711,0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753,0754,0755,0756,0757,0758,0759,0760,0761,0762
superseded_by: 0851
---

# Attempt counters bump-before-run means max-attempt is always unprotected

Both `get_issue_attempts` and `get_auto_agent_attempts` in this repo are incremented *before* the run starts and cleared on close/success. A retry-window guard written as `0 < attempts < max_attempts` therefore never protects the final attempt (`attempts == max`), since that run is in-flight but the bound excludes it.

Example: this is an accepted, theoretical residual race in `src/workspace_gc_loop.py` — not a regression to fix inline; closing it fully requires a live session lock/heartbeat, tracked as a `hydraflow-find` follow-up rather than blocking the fix.

**Why:** documents why the last-attempt gap is intentional scope-out, so future readers don't re-flag it as an unfixed bug.
