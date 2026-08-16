---
id: 2662
topic: testing
source_issue: 11286
source_phase: plan
created_at: 2026-08-16T01:54:47.585510+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Cross-check fixable ID sets against registry.all_registered()

Rule: Any hardcoded check-ID set in `scripts/hydraflow_audit/` must be cross-validated against `registry.all_registered()` in tests.

Example: `MECHANICALLY_FIXABLE_CHECK_IDS = {"P8.1","P8.2","P8.3","P8.5"}` is tested so every member is a key of `registry.all_registered()`.

**Why:** Without the cross-check, stale or typo'd IDs silently match nothing — the set looks correct but remediates zero violations.
