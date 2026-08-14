---
id: 1842
topic: patterns
source_issue: 11132
source_phase: plan
created_at: 2026-08-14T12:40:51.197489+00:00
status: superseded
corroborations: 1
superseded_by: 1939
---

# Roll forward legacy buckets — never fabricate zeros for missing keys

When introducing new counter keys into `src/prompt_telemetry.py`, a bucket written before the fix must accumulate forward from its next record, not be backfilled with a fabricated zero.

- Use `_as_int(target.get(k, 0)) + _as_int(record.get(k, 0))` so a legacy bucket picks up the key only when a post-fix record lands.
- A legacy bucket with no subsequent record still omits both keys entirely.
- This keeps "never tracked" distinguishable from "tracked, zero" in `pr_stats.json`.

**Why:** Backfilling zeros destroys the semantic distinction between a source that had zero cache usage and one that predates cache tracking.
