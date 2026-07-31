---
id: 1842
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T06:59:05.750797+00:00
status: superseded
corroborations: 1
supersedes: 1737
superseded_by: 1969
---

# Loop default interval must be min() of class-specific floors

_get_default_interval in src/triage_retry_loop.py must return `min(triage_retry_interval, triage_infra_retry_interval)`, not just the original 24h value.

Example: adding a shorter per-class retry floor without tightening the loop's own tick cadence leaves that floor dead code.

**Why:** If the loop's polling interval stays slower than a newly-added short floor, the loop never wakes up in time to act on it.
