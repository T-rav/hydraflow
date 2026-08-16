---
id: 0383
topic: architecture
source_issue: 11326
source_phase: plan
created_at: 2026-08-16T09:29:42.917651+00:00
status: active
corroborations: 1
---

# Run make arch-regen-stage and full make quality for additive code

Run `make arch-regen-stage` before committing any new `src/*.py` module, and execute the full `make quality` suite.

Example: Adding `src/class_key.py` requires regenerating `docs/arch/generated/*`.

**Why:** CI fails on stale architecture artifacts, and additive helpers have a wider blast radius than their diff suggests.
