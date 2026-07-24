---
id: 0698
topic: gotchas
source_issue: 10457
source_phase: plan
created_at: 2026-07-24T12:45:53.971751+00:00
status: active
corroborations: 1
---

# FLEET-<pr> rollup dedup must fail-closed on missing/errored members

`FLEET-<pr>` batched rollups in `src/adr_drift_resolver_loop.py` aggregate multiple ADRs under one issue. Only write the `dedup_store` key `adr_drift_resolver:FLEET-<pr>:<issue#>` when every member ADR resolved definitively (all CONSISTENT → close, any non-CONSISTENT → stay open). A missing/renumbered member ADR or a `triage.classify` error must withhold dedup entirely so the whole batch retries next tick — never fingerprint a partially-triaged batch.

**Why:** A swallowed member error that still writes dedup would mark a batch as "handled" even though a real drift was never triaged.
