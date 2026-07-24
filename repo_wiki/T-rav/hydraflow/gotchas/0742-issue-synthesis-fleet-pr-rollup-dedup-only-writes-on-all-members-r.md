---
id: 0742
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T15:44:16.023653+00:00
status: active
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
---

# FLEET-<pr> rollup dedup only writes on all-members-resolved outcome

`AdrDriftResolverLoop` (src/adr_drift_resolver_loop.py) must only write the `dedup_store` key `adr_drift_resolver:FLEET-<pr>:<issue#>` — and only auto-close the rollup — when every member ADR resolves definitively: all CONSISTENT closes the batch, any non-CONSISTENT keeps it open.

Example: a missing/renumbered member ADR, a `triage.classify` error on one member, or a fleet entry missing `adr_numbers` must withhold dedup entirely so the batch retries next tick; member triages still count against `max_triage_per_tick`.

**Why:** A swallowed member error or partially-triaged batch that still writes dedup would mark a real drift as "handled" and silently stop tracking it, while also bounding per-tick LLM cost on large fleets.
