---
id: 0219
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T04:51:57.148635+00:00
status: active
corroborations: 1
supersedes: 0204
---

# fixability.py imports are one-way: models→fixability, never reverse

`scripts/hydraflow_audit/fixability.py` must NOT import `models.py`; `models.py` imports `fixability` one-way.

Example: `fixability.py` defines `MECHANICALLY_FIXABLE_CHECK_IDS` and `is_mechanically_fixable()` with zero models dependency. `Finding.__post_init__` in `models.py` calls `is_mechanically_fixable(self.check_id)`.

**Why:** A reverse import creates a circular dependency that breaks module loading for the entire `hydraflow_audit` package.
