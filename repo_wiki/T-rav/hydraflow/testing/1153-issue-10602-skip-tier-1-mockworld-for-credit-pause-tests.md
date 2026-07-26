---
id: 1153
topic: testing
source_issue: 10602
source_phase: plan
created_at: 2026-07-26T10:26:40.201309+00:00
status: active
corroborations: 1
---

# Skip Tier-1 MockWorld for credit pause tests

Skip Tier-1 MockWorld tests for credit pause/resume behaviors. Use Tier-2 `tests/sandbox_scenarios/` instead. `MockWorld.run_pipeline` drives phases directly with no `_supervise_loops`, so a credit pause cannot be modeled there. **Why:** Prevents test suites from hanging or falsely failing when evaluating `_pause_for_credits` or `_sleep_until_resume`.
