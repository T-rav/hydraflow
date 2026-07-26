---
id: 0919
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:15:44.774461+00:00
status: superseded
corroborations: 1
supersedes: 0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797,0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0826,0827,0828,0829,0830,0833,0834,0838,0839,0840,0841,0842,0843,0844,0848,0848,0848,0849,0850
superseded_by: 0940
---

# Scope EscapeLedgerLoop surfacing dedup keys per reason, not per record

A single `surfaced:<id>` key in `src/escape_ledger_loop.py` conflates independent surfacing criteria (low-confidence attribution vs. unencoded aging past `escape_ledger_encoding_age_days`) — spending the key on the first-fired reason silently suppresses the other forever. Fix: key as `surfaced:<reason>:<id>` with named constants (e.g. `REASON_LOW_CONFIDENCE`, `REASON_AGING`), and have `select_findings_to_surface` return `(record, reasons)` pairs listing only unspent criteria. A record eligible under both reasons at once files one issue naming both and spends both keys.

**Why:** Without reason-scoping, the 14-day aging surface in `select_findings_to_surface` is dead code — any record already surfaced once for a different reason can never re-fire.
