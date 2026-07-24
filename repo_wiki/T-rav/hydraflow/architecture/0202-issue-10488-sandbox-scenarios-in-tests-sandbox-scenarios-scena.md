---
id: 0202
topic: architecture
source_issue: 10488
source_phase: plan
created_at: 2026-07-24T21:53:09.549138+00:00
status: active
corroborations: 1
---

# Sandbox scenarios in tests/sandbox_scenarios/scenarios/ auto-discover

New scenario files (e.g. `tests/sandbox_scenarios/scenarios/s88_pipeline_flow_counts.py`) require no manual registration — `runner/loader.py` auto-discovers files in that directory. Also wire the scenario into `tests/scenarios/test_sandbox_parity.py` so it's exercised at tier-1, not just sandbox tier.

**Why:** avoids writing a scenario file and separately hunting for a registry/index to update — there isn't one for this loader.
