---
id: 0889
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:15:44.740602+00:00
status: superseded
corroborations: 1
supersedes: 0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797,0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0826,0827,0828,0829,0830,0833,0834,0838,0839,0840,0841,0842,0843,0844,0848,0848,0848,0849,0850
superseded_by: 0940
---

# FLEET-<pr> rollup dedup fails closed on non-CONSISTENT or errored members

`AdrDriftResolverLoop` only auto-closes / dedupes a `FLEET-<pr>` rollup when triage classifies every member ADR as CONSISTENT — any non-CONSISTENT, missing, or errored member leaves the batch open and un-deduped so it retries next tick.

Example: only write dedup_store key `adr_drift_resolver:FLEET-<pr>:<issue#>` on a definitive all/mixed outcome; a `triage.classify` error or missing/renumbered member ADR withholds dedup entirely, and a fleet entry missing `adr_numbers` is skipped rather than crashed. Member triages count against `max_triage_per_tick`.

**Why:** Fingerprinting a partially-triaged batch as "handled" would let a real drift silently escape re-triage, and a single flaky/slow member triage would otherwise close a batch that still has genuine drift.
