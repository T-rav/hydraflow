---
id: 2734
topic: testing
source_issue: 11409
source_phase: plan
created_at: 2026-08-18T03:04:36.397155+00:00
status: active
corroborations: 1
---

# Use real HydraFlowConfig, not MagicMock, for persistence-seam scenarios

Rule: In `tests/scenarios/test_wiki_evolution_scenarios.py`, construct a real `HydraFlowConfig` when the scenario touches the fingerprint gate's persistence layer — the gate persists state under `data_path()`.

**Why:** A `MagicMock` config bypasses the persistence seam entirely: the state file is never written or read, so fail-open and recompile behavior cannot be exercised and the scenario passes vacuously.
