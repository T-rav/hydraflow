---
id: 1938
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T14:29:27.128456+00:00
status: superseded
corroborations: 1
supersedes: 1841
superseded_by: 2046
---

# Counter shape has two writers — change _new_counter and _accumulate together

`_new_counter()` (init shape) and `_accumulate_counter()` (merge shape) in `src/prompt_telemetry.py` are the two writers of the aggregate counter dict. Any key added to one must be added to the other.

- If only `_accumulate_counter()` sums a new key, fresh buckets (via `_new_counter()`) lack it and `.get(k, 0)` masks the divergence.
- If only `_new_counter()` initializes it, rolled-forward legacy buckets never gain the key.

**Why:** Fresh vs. rolled-forward buckets silently diverge, producing inconsistent `pr_stats.json` output depending on when a bucket was first created.
