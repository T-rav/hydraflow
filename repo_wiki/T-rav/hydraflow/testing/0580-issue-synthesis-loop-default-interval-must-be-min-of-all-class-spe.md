---
id: 0580
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:13:41.471492+00:00
status: active
corroborations: 1
supersedes: 0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566
---

# Loop default interval must be min() of all class-specific floors

In `src/triage_retry_loop.py`, `_get_default_interval` has to return `min(triage_retry_interval, triage_infra_retry_interval)`, not just the original 24h value. If the loop's own tick cadence stays slower than a newly-added short floor, that floor becomes dead code — the loop never wakes up in time to act on it.

**Why:** adding a shorter per-class retry floor is silently ineffective unless the loop's polling interval is also tightened to match the shortest configured floor.
