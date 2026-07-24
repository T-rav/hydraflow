---
id: 0566
topic: testing
source_issue: 10290
source_phase: plan
created_at: 2026-07-22T17:18:40.189874+00:00
status: superseded
corroborations: 1
superseded_by: 0567
---

# Loop default interval must be min() of all class-specific floors

In `src/triage_retry_loop.py`, `_get_default_interval` has to return `min(triage_retry_interval, triage_infra_retry_interval)`, not just the original 24h value. If the loop's own tick cadence stays slower than a newly-added short floor, that floor becomes dead code — the loop never wakes up in time to act on it.

**Why:** adding a shorter per-class retry floor is silently ineffective unless the loop's polling interval is also tightened to match the shortest configured floor.
