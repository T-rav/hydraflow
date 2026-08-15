---
id: 1336
topic: gotchas
source_issue: 11170
source_phase: plan
created_at: 2026-08-14T20:23:54.672678+00:00
status: active
corroborations: 1
---

# Keep check #6 errors aggregated with 'immutability' header

Check #6 in `scripts/check_console_conformance.py` must emit exactly one aggregated error whose body lists each violation; the header must retain the literal word 'immutability'.

Example: a sibling pin in `tests/` filters errors on the substring 'immutability'; splitting into per-change errors breaks that filter.

**Why:** A regression test asserts one error containing that token; per-change splitting causes the count or substring assertion to fail even when violations are correctly detected.
