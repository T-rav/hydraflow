---
id: 1955
topic: testing
source_issue: 10898
source_phase: plan
created_at: 2026-07-31T11:06:20.726251+00:00
status: active
corroborations: 1
---

# Counter-pin tests enforce intentional behavior that looks buggy

`test_skipped_and_cancelled_are_not_attempts` in `tests/test_gate_health_loop.py` asserts skipped/cancelled are NOT counted as attempts — this is a counter-pin, not a bug to fix.

When adding dormancy tracking to `JobStats`, keep this test intact and green; extend `TestTallyJobStats` with the new dormant-counter assertions alongside it.

**Why:** The distinction between "drop attempts" (terminal-only rates) and "drop evidence" (dormant records discarded entirely) is load-bearing; conflating them silently breaks rate calculations.
