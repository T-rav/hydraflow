---
id: 2535
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.075574+00:00
status: active
corroborations: 1
supersedes: 2346
---

# Counter-pin tests enforce intentional behavior that looks buggy

`test_skipped_and_cancelled_are_not_attempts` in `tests/test_gate_health_loop.py` asserts skipped/cancelled are NOT counted as attempts — this is a counter-pin, not a bug to fix.

Example: when adding dormancy tracking to `JobStats`, keep this test intact and green; extend `TestTallyJobStats` with the new dormant-counter assertions alongside it.

**Why:** The distinction between 'drop attempts' (terminal-only rates) and 'drop evidence' (dormant records discarded entirely) is load-bearing; conflating them silently breaks rate calculations.
