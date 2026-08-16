---
id: 3572
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T12:13:22.941644+00:00
status: active
corroborations: 1
supersedes: 3425
---

# Roll forward legacy buckets — never fabricate zeros for missing keys

When introducing new counter keys into `src/prompt_telemetry.py`, a bucket written before the fix must accumulate forward from its next record, not be backfilled with a fabricated zero.

Example: Use `_as_int(target.get(k, 0)) + _as_int(record.get(k, 0))` so a legacy bucket picks up the key only when a post-fix record lands; a bucket with no subsequent record still omits both keys, keeping "never tracked" distinguishable from "tracked, zero". See also: [patterns] — Counter shape has two writers.

**Why:** Backfilling zeros destroys the semantic distinction between a source that had zero cache usage and one that predates cache tracking.
