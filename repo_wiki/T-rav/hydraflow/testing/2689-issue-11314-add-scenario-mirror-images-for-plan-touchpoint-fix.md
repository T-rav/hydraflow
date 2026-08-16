---
id: 2689
topic: testing
source_issue: 11314
source_phase: plan
created_at: 2026-08-16T07:29:20.234661+00:00
status: active
corroborations: 1
---

# Add scenario mirror images for plan touchpoint fixes

When fixing a plan gate logic escape, add a scenario to `tests/scenarios/test_plan_touchpoint_expander_scenario.py` (e.g., S6 mirroring S4). Use MockWorld to verify an unclassified issue reaches READY **with** a reviewer spawn via `plan_issues`.

**Why:** Unit tests validating the gate function alone miss integration escapes. Scenario tests prove the fix propagates through the actual `plan_issues` pipeline, not just the isolated gate logic.
