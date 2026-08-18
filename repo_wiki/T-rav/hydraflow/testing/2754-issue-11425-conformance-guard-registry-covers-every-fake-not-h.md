---
id: 2754
topic: testing
source_issue: 11425
source_phase: plan
created_at: 2026-08-18T04:29:33.971203+00:00
status: active
corroborations: 1
---

# Conformance guard: registry covers every fake, not hand-listed pairs

`tests/test_mockworld_fakes_conformance.py` must registry-check every fake exported by `mockworld.fakes.__all__` with a resolvable reference type — never one hand-listed pair.
- Removing a pair from the registry must fail the guard, not shrink coverage.
- The comparator must be kind-aware: a fake redeclaring a reference method's positional param as keyword-only is rejected; `*args`/`**kwargs` absorb patterns stay compatible.
**Why:** A hand-listed registry silently lets new fakes ship untested; only a full-surface registry with a kind-aware comparator catches positional→keyword-only narrowing drift.
