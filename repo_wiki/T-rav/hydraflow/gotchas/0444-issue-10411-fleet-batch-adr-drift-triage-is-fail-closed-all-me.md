---
id: 0444
topic: gotchas
source_issue: 10411
source_phase: plan
created_at: 2026-07-24T05:57:06.014384+00:00
status: active
corroborations: 1
---

# Fleet-batch ADR-drift triage is fail-closed: all members must be CONSISTENT to auto-close

`AdrDriftResolverLoop` only auto-closes a `FLEET-<pr>` rollup when triage classifies **every** member ADR as CONSISTENT; any non-CONSISTENT member leaves the batch open and HITL-labeled. Member triages count against `max_triage_per_tick`, and a partially-triaged batch is not deduped so it retries next tick; a triage error on one member keeps the whole batch open. A fleet entry missing `adr_numbers` is skipped, not crashed. **Why:** prevents a single flaky/slow member triage from silently closing a batch that still has a real drift, and bounds per-tick LLM cost on large fleets.
