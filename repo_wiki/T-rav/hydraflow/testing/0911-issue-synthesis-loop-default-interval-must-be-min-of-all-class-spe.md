---
id: 0911
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:46:40.767723+00:00
status: superseded
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
superseded_by: 0954
---

# Loop default interval must be min() of all class-specific floors

`_get_default_interval` in `src/triage_retry_loop.py` must return `min(triage_retry_interval, triage_infra_retry_interval)`, not just the original 24h value.

Example: adding a shorter per-class retry floor without tightening the loop's own tick cadence leaves that floor dead code.

**Why:** if the loop's polling interval stays slower than a newly-added short floor, the loop never wakes up in time to act on it.
