---
id: 2718
topic: testing
source_issue: 11338
source_phase: plan
created_at: 2026-08-16T12:34:38.645208+00:00
status: active
corroborations: 1
---

# test_sandbox_parity.py is the release-gating scenario tier

`tests/scenarios/test_sandbox_parity.py` re-runs every sandbox scenario in-process. When changing fake behavior or seed values, this tier IS the scenario coverage — no new scenario file is needed when the behavior under change is the seeds themselves.

Pair it with sandbox e2e on scenarios where seeded PR branch differs from implement branch: `python scripts/sandbox_scenario.py run <NAME>`.

**Why:** Adding redundant scenario files duplicates coverage; the parity tier already exercises the changed code paths across all scenarios, making it the correct gate for seed-level behavioral changes.
