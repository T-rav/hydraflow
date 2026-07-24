---
id: 0759
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T15:44:16.349956+00:00
status: active
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
---

# Attempt counters bump-before-run leave max-attempt unprotected

Both `get_issue_attempts` and `get_auto_agent_attempts` in this repo are incremented *before* the run starts and cleared on close/success. A retry-window guard written as `0 < attempts < max_attempts` therefore never protects the final attempt (`attempts == max`), since that run is in-flight but the bound excludes it.

Example: this is an accepted, theoretical residual race in `src/workspace_gc_loop.py` — not a regression to fix inline; closing it fully requires a live session lock/heartbeat, tracked as a `hydraflow-find` follow-up rather than blocking the fix.

**Why:** Documents why the last-attempt gap is intentional scope-out, so future readers don't re-flag it as an unfixed bug.
