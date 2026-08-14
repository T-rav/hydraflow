---
id: 1939
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T14:29:27.143548+00:00
status: active
corroborations: 1
supersedes: 1842
---

# Roll forward legacy buckets — never fabricate zeros for missing keys

When introducing new counter keys into `src/prompt_telemetry.py`, a bucket written before the fix must accumulate forward from its next record, not be backfilled with a fabricated zero.

- Use `_as_int(target.get(k, 0)) + _as_int(record.get(k, 0))` so a legacy bucket picks up the key only when a post-fix record lands.
- A legacy bucket with no subsequent record still omits both keys entirely.
- This keeps "never tracked" distinguishable from "tracked, zero" in `pr_stats.json`.

**Why:** Backfilling zeros destroys the semantic distinction between a source that had zero cache usage and one that predates cache tracking.
