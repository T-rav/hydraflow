---
id: 0801
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T01:13:09.946536+00:00
status: active
corroborations: 1
supersedes: 0704,0705,0706,0707,0708,0709,0710,0711,0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753,0754,0755,0756,0757,0758,0759,0760,0761,0762
---

# FLEET-<pr> rollup dedup fails closed on non-CONSISTENT or errored members

`AdrDriftResolverLoop` only auto-closes / dedupes a `FLEET-<pr>` rollup when triage classifies every member ADR as CONSISTENT — any non-CONSISTENT, missing, or errored member leaves the batch open and un-deduped so it retries next tick.

Example: only write dedup_store key `adr_drift_resolver:FLEET-<pr>:<issue#>` on a definitive all/mixed outcome; a `triage.classify` error or missing/renumbered member ADR withholds dedup entirely, and a fleet entry missing `adr_numbers` is skipped rather than crashed. Member triages count against `max_triage_per_tick`.

**Why:** Fingerprinting a partially-triaged batch as "handled" would let a real drift silently escape re-triage, and a single flaky/slow member triage would otherwise close a batch that still has genuine drift.
