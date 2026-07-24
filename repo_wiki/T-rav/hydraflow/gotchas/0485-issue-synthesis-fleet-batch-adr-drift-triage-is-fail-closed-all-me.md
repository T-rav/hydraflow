---
id: 0485
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:27:31.405244+00:00
status: active
corroborations: 1
supersedes: 0402,0403,0404,0405,0406,0407,0408,0409,0410,0411,0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445
---

# Fleet-batch ADR-drift triage is fail-closed: all members must be CONSISTENT to auto-close

`AdrDriftResolverLoop` only auto-closes a `FLEET-<pr>` rollup when triage classifies **every** member ADR as CONSISTENT; any non-CONSISTENT member leaves the batch open and HITL-labeled. Member triages count against `max_triage_per_tick`, and a partially-triaged batch is not deduped so it retries next tick; a triage error on one member keeps the whole batch open. A fleet entry missing `adr_numbers` is skipped, not crashed.

**Why:** prevents a single flaky/slow member triage from silently closing a batch that still has a real drift, and bounds per-tick LLM cost on large fleets.
