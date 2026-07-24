---
id: 0681
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:40:13.477531+00:00
status: active
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631,0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642
---

# Fleet-batch ADR-drift triage auto-closes only when all members CONSISTENT

`AdrDriftResolverLoop` only auto-closes a `FLEET-<pr>` rollup when triage classifies every member ADR as CONSISTENT; any non-CONSISTENT member leaves the batch open and HITL-labeled.

Example: member triages count against `max_triage_per_tick`, and a partially-triaged batch is not deduped so it retries next tick; a triage error on one member keeps the whole batch open. A fleet entry missing `adr_numbers` is skipped, not crashed.

**Why:** Prevents a single flaky/slow member triage from silently closing a batch that still has a real drift, and bounds per-tick LLM cost on large fleets.
