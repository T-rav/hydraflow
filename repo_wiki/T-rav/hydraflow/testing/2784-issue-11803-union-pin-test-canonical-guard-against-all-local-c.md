---
id: 2784
topic: testing
source_issue: 11803
source_phase: plan
created_at: 2026-08-30T09:12:38.105445+00:00
status: active
corroborations: 1
---

# Union pin: test canonical guard against all local copies

When deduplicating a guard, add a drift tripwire: parametrize over all live local copies × the sentinel matrix (truthy, falsy, absent) and assert verdict equality.

`flow_stopped` in `src/flows/guards.py` is tested against `_flow_stopped` from `src/plan_phase_common.py`, `src/implement_phase/_common.py`, and `src/review_phase/_flow.py` across the same state inputs. If a local copy drifts later, this test fails.

**Why:** Without a union pin, local copies drift independently until the migration child binds them, causing silent behaviour divergence.
