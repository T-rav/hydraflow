---
id: 2793
topic: patterns
source_issue: 11238
source_phase: plan
created_at: 2026-08-15T09:37:15.548512+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Always include source loop in _affected_loops on credit pause

Always append `source` to the set returned by `_affected_loops`, regardless of how the source loop was provider-classified.

Example: An anthropic cap raised by a zai-classified `implement` loop must still include `implement` in `_affected_loops` so it gets recreated on resume.

**Why:** Omitting the source loop leaves it un-recreated after pause ends, causing the supervisor to hot-loop its dead task (#9924).
