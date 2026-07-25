---
id: 0922
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:15:44.777896+00:00
status: active
corroborations: 1
supersedes: 0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797,0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0826,0827,0828,0829,0830,0833,0834,0838,0839,0840,0841,0842,0843,0844,0848,0848,0848,0849,0850
---

# Escape ledger: distinguish 'blind' (no signal) from 'live' (0 confirmed) gauges

A metric reading 0.00 is ambiguous between "gate is perfect" and "gate can't see anything." `escape/metrics.gauge_calibration()` resolves this for the confirmed-escape rate: status is `live` when ≥1 CONFIRMED row exists in the window, `blind` when all rows are low-confidence or the ledger is empty. `report.py`'s headline renders this status plus a high/medium/low confidence breakdown so `escape-ledger.md` falsifies gate quality instead of reporting a permanent, uninformative 0.00.

**Why:** without a calibration signal, a broken detector (see the splitlines bug above) and a genuinely clean codebase are indistinguishable in the rendered report.
