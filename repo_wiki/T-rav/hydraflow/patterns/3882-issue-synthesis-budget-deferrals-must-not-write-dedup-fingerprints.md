---
id: 3882
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T15:30:57.907427+00:00
status: superseded
corroborations: 1
supersedes: 3737
superseded_by: 4029
---

# Budget deferrals must not write dedup fingerprints or mark rollups handled

When deferring a fleet batch in `AdrDriftResolverLoop._do_work` for budget reasons, do not call `dedup.set_all` or mark the rollup handled — the batch must remain an open candidate for the next tick.

Example: Only triaged or substantively-skipped batches persist dedup state via `dedup.set_all`. Deferred batches write no fingerprint and appear unchanged in faked state.

**Why:** Writing a dedup fingerprint or handled mark on deferral permanently loses the batch, as future ticks will see it as already processed and skip it.
