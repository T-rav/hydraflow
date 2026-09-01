---
id: 2807
topic: testing
source_issue: 11948
source_phase: plan
created_at: 2026-09-01T10:57:18.007854+00:00
status: active
corroborations: 1
---

# exempt_lanes strings must match call-site lane constants exactly

`exempt_lanes` in `policy.yaml` must use the same lane string that the call site passes to `enforce_merge_policy(..., lane=...)`. An `rc/*` promotion diff trivially matches `src/*_loop.py` and exceeds 20 files — a string mismatch silently stalls `staging→main`.

Bind lane names to the constants the call sites pass, and cover both mechanical lanes (`staging_promotion_loop`, `dependabot_merge_loop`) with tests.

**Why:** Prevents silent merge refusal on mechanical lanes when a size-matched substantial-change class is added.
