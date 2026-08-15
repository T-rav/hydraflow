---
id: 2300
topic: patterns
source_issue: 11184
source_phase: plan
created_at: 2026-08-14T23:44:16.701452+00:00
status: superseded
corroborations: 1
superseded_by: 2420
---

# Budget deferrals must not write dedup fingerprints or mark rollups handled

When deferring a fleet batch in `AdrDriftResolverLoop._do_work` for budget reasons, do not call `dedup.set_all` or mark the rollup handled — the batch must remain an open candidate for the next tick.

- Only triaged or substantively-skipped batches persist dedup state via `dedup.set_all`.
- Deferred batches write no fingerprint and appear unchanged in faked state.

**Why:** Writing a dedup fingerprint or handled mark on deferral permanently loses the batch, as future ticks will see it as already processed and skip it.
