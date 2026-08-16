---
id: 0204
topic: dependencies
source_issue: 11286
source_phase: plan
created_at: 2026-08-16T01:54:47.585468+00:00
status: superseded
corroborations: 1
superseded_by: 0219
---

# fixability.py imports are one-way: models→fixability, never reverse

Rule: `scripts/hydraflow_audit/fixability.py` must NOT import `models.py`; `models.py` imports `fixability` one-way.

Example: `fixability.py` defines `MECHANICALLY_FIXABLE_CHECK_IDS` and `is_mechanically_fixable()` with zero models dependency. `Finding.__post_init__` in `models.py` calls `is_mechanically_fixable(self.check_id)`.

**Why:** A reverse import creates a circular dependency that breaks module loading for the entire `hydraflow_audit` package.
