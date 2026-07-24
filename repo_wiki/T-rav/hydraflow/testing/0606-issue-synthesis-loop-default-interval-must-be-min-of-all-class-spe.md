---
id: 0606
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:57:59.581495+00:00
status: active
corroborations: 1
supersedes: 0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
---

# Loop default interval must be min() of all class-specific floors

In `src/triage_retry_loop.py`, `_get_default_interval` has to return `min(triage_retry_interval, triage_infra_retry_interval)`, not just the original 24h value. If the loop's own tick cadence stays slower than a newly-added short floor, that floor becomes dead code — the loop never wakes up in time to act on it.

**Why:** adding a shorter per-class retry floor is silently ineffective unless the loop's polling interval is also tightened to match the shortest configured floor.
