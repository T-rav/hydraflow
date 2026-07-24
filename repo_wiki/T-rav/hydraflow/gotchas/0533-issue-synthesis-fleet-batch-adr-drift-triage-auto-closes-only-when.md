---
id: 0533
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:05:16.799883+00:00
status: active
corroborations: 1
supersedes: 0446,0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0492,0493
---

# Fleet-batch ADR-drift triage auto-closes only when all members CONSISTENT

`AdrDriftResolverLoop` only auto-closes a `FLEET-<pr>` rollup when triage classifies every member ADR as CONSISTENT; any non-CONSISTENT member leaves the batch open and HITL-labeled.

Example: member triages count against `max_triage_per_tick`, and a partially-triaged batch is not deduped so it retries next tick; a triage error on one member keeps the whole batch open. A fleet entry missing `adr_numbers` is skipped, not crashed.

**Why:** Prevents a single flaky/slow member triage from silently closing a batch that still has a real drift, and bounds per-tick LLM cost on large fleets.
