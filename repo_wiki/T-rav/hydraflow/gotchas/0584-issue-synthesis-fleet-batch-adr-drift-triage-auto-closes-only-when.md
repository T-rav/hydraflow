---
id: 0584
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:39:28.223806+00:00
status: active
corroborations: 1
supersedes: 0494,0495,0496,0497,0498,0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522,0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539
---

# Fleet-batch ADR-drift triage auto-closes only when all members CONSISTENT

`AdrDriftResolverLoop` only auto-closes a `FLEET-<pr>` rollup when triage classifies every member ADR as CONSISTENT; any non-CONSISTENT member leaves the batch open and HITL-labeled.

Example: member triages count against `max_triage_per_tick`, and a partially-triaged batch is not deduped so it retries next tick; a triage error on one member keeps the whole batch open. A fleet entry missing `adr_numbers` is skipped, not crashed.

**Why:** Prevents a single flaky/slow member triage from silently closing a batch that still has a real drift, and bounds per-tick LLM cost on large fleets.
