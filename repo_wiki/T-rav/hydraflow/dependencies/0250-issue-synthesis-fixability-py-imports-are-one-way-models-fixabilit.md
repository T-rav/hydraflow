---
id: 0250
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T12:24:40.979322+00:00
status: superseded
corroborations: 1
supersedes: 0234
superseded_by: 0268
---

# fixability.py imports are one-way: models→fixability, never reverse

`scripts/hydraflow_audit/fixability.py` must NOT import `models.py`; `models.py` imports `fixability` one-way.

Example: `fixability.py` defines `MECHANICALLY_FIXABLE_CHECK_IDS` and `is_mechanically_fixable()` with zero models dependency. `Finding.__post_init__` in `models.py` calls `is_mechanically_fixable(self.check_id)`.

**Why:** A reverse import creates a circular dependency that breaks module loading for the entire `hydraflow_audit` package.
