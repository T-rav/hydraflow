---
id: 1347
topic: gotchas
source_issue: 11181
source_phase: plan
created_at: 2026-08-14T23:04:04.877863+00:00
status: active
corroborations: 1
---

# triaged/fleet_triaged are success-only stats; add separate attempt counter

Do not redefine `triaged` or `fleet_triaged` in `src/adr_drift_resolver_loop.py` to include errors; existing tests and status consumers depend on their success-only semantics. Add a separate `calls_spent` counter for budget accounting.

The fix for #11181 adds `calls_spent` to the tick result dict alongside `triaged`, keeping the latter's meaning unchanged while making the budget invariant assertable by downstream consumers.

**Why:** Overloading an existing stat's meaning breaks downstream assertions and status reporting silently — the bug you're fixing becomes a new bug elsewhere.
