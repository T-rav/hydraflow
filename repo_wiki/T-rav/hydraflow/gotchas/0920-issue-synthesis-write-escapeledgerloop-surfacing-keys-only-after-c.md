---
id: 0920
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:15:44.775619+00:00
status: superseded
corroborations: 1
supersedes: 0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797,0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0826,0827,0828,0829,0830,0833,0834,0838,0839,0840,0841,0842,0843,0844,0848,0848,0848,0849,0850
superseded_by: 0940
---

# Write EscapeLedgerLoop surfacing keys only after create_issue succeeds

In `_surface_findings`, mark a reason's dedup key spent only after the corresponding `create_issue` call returns successfully — never before. If the call fails, all keys for that tick stay unspent so the record retries next tick. `CreditExhaustedError` from `create_issue` must still propagate out of `_surface_findings` unchanged (per `reraise_on_credit_or_bug`); don't swallow it while adding the per-reason write logic.

**Why:** Marking keys before the write completes would permanently lose a surfacing on a transient GitHub API failure, since EscapeLedger keys are never retroactively un-spent.
