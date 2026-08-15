---
id: 1376
topic: gotchas
source_issue: 11211
source_phase: review
created_at: 2026-08-15T06:58:01.011527+00:00
status: active
corroborations: 1
---

# Log reroutes for all spawn-routing dials, not just failovers

Emit an info log line for any per-repo spawn reroute, matching the standard set by `apply_credit_failover`.
- **Example:** In `src/base_runner.py`, `apply_repo_provider` initially emitted no log during its standard reroute, making it invisible compared to the exceptional failover path 6 lines below.
- **Why:** Without parity logging, standing per-repo reroutes are invisible in logs at lower fidelity than exceptional failover paths, complicating tracing.
