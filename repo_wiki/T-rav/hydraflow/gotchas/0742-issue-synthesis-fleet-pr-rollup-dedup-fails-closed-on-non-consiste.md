---
id: 0742
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:18:53.873998+00:00
status: superseded
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
superseded_by: 0764
---

# FLEET-<pr> rollup dedup fails closed on non-CONSISTENT or errored members

`AdrDriftResolverLoop` only auto-closes / dedupes a `FLEET-<pr>` rollup when triage classifies every member ADR as CONSISTENT — any non-CONSISTENT, missing, or errored member leaves the batch open and un-deduped so it retries next tick.

Example: only write dedup_store key `adr_drift_resolver:FLEET-<pr>:<issue#>` on a definitive all/mixed outcome; a `triage.classify` error or missing/renumbered member ADR withholds dedup entirely, and a fleet entry missing `adr_numbers` is skipped rather than crashed. Member triages count against `max_triage_per_tick`.

**Why:** Fingerprinting a partially-triaged batch as "handled" would let a real drift silently escape re-triage, and a single flaky/slow member triage would otherwise close a batch that still has genuine drift.
