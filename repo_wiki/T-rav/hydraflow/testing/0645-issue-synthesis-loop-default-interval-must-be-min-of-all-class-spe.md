---
id: 0645
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:31:08.492183+00:00
status: superseded
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631
superseded_by: 0672
---

# Loop default interval must be min() of all class-specific floors

In `src/triage_retry_loop.py`, `_get_default_interval` has to return `min(triage_retry_interval, triage_infra_retry_interval)`, not just the original 24h value. If the loop's own tick cadence stays slower than a newly-added short floor, that floor becomes dead code — the loop never wakes up in time to act on it.

**Why:** adding a shorter per-class retry floor is silently ineffective unless the loop's polling interval is also tightened to match the shortest configured floor.
