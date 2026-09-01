---
id: 1548
topic: gotchas
source_issue: 11865
source_phase: plan
created_at: 2026-09-01T05:42:59.837537+00:00
status: active
corroborations: 1
---

# Cross-module imports must not reference _-prefixed symbols

When importing across modules in `src/`, never import a `_`-prefixed name. If a needed helper lands as private (e.g., #11860's actor-enumeration function in `charter.py`), add a public wrapper in the owning module before `charter_drift_caretaker_loop.py` imports it.

- Importing `_enumerate_actors` cross-module violates the gotchas audit gate
- Add `enumerate_actors` as a public wrapper instead

**Why:** Private names signal implementation detail; cross-module coupling on them makes refactors silently break downstream callers and fails the repo's gotchas audit.
