---
id: 0921
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:15:44.776759+00:00
status: active
corroborations: 1
supersedes: 0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797,0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0826,0827,0828,0829,0830,0833,0834,0838,0839,0840,0841,0842,0843,0844,0848,0848,0848,0849,0850
---

# EscapeLedgerLoop max_per_tick caps selected records, not surfacing reasons

When a record can carry multiple unspent reasons (low-confidence + aging), `max_per_tick` in `select_findings_to_surface` must still count it as one selection toward the cap, not one per reason — otherwise a single dual-reason record could consume two slots of budget for one issue. Test explicitly: 20 eligible rows with `max_per_tick=3` yields exactly 3 selections and `capped is True`.

**Why:** Counting reasons instead of records would make the per-tick issue-filing budget inconsistent with the one-issue-per-record-per-tick invariant the loop otherwise guarantees.
