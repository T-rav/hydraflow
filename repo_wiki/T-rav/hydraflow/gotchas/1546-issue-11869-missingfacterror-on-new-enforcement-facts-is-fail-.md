---
id: 1546
topic: gotchas
source_issue: 11869
source_phase: plan
created_at: 2026-09-01T05:42:49.576655+00:00
status: active
corroborations: 1
---

# MissingFactError on new enforcement facts is fail-closed, not a bug

When adding a fact to `_ENFORCEMENT_REQUIRED` in `src/policy/python_engine.py`, expect existing fixture-built fact sets to redden with `MissingFactError`; fix the fixtures, do not weaken the requirement.

Example: adding `binds` as the 5th enforcement fact caused all pre-existing fixture sets to fail until each gained a `binds` value.

**Why:** `MissingFactError` is the fail-closed contract — silently defaulting would mask missing observations in production ADR scans.
