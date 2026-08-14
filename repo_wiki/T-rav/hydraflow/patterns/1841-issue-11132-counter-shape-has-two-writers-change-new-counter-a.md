---
id: 1841
topic: patterns
source_issue: 11132
source_phase: plan
created_at: 2026-08-14T12:40:51.197450+00:00
status: active
corroborations: 1
---

# Counter shape has two writers — change _new_counter and _accumulate together

`_new_counter()` (init shape) and `_accumulate_counter()` (merge shape) in `src/prompt_telemetry.py` are the two writers of the aggregate counter dict. Any key added to one must be added to the other.

- If only `_accumulate_counter()` sums a new key, fresh buckets (via `_new_counter()`) lack it and `.get(k, 0)` masks the divergence.
- If only `_new_counter()` initializes it, rolled-forward legacy buckets never gain the key.

**Why:** Fresh vs. rolled-forward buckets silently diverge, producing inconsistent `pr_stats.json` output depending on when a bucket was first created.
