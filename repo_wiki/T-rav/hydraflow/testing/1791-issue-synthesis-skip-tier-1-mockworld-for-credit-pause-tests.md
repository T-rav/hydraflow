---
id: 1791
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T04:20:59.117145+00:00
status: active
corroborations: 1
supersedes: 1697
---

# Skip Tier-1 MockWorld for credit pause tests

Skip Tier-1 MockWorld tests for credit pause/resume behaviors. Use Tier-2 tests/sandbox_scenarios/ instead. MockWorld.run_pipeline drives phases directly with no _supervise_loops, so a credit pause cannot be modeled there.

Example: use sandbox scenarios for testing _pause_for_credits or _sleep_until_resume.

**Why:** Prevents test suites from hanging or falsely failing when evaluating credit pause behaviors.
