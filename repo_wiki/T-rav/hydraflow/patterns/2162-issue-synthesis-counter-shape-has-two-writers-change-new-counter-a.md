---
id: 2162
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T23:28:16.569537+00:00
status: active
corroborations: 1
supersedes: 2046
---

# Counter shape has two writers — change _new_counter and _accumulate together

Any key added to `_new_counter()` must also be added to `_accumulate_counter()` in `src/prompt_telemetry.py` — both write the aggregate counter dict shape.

Example: If only `_accumulate_counter()` sums a new key, fresh buckets (via `_new_counter()`) lack it and `.get(k, 0)` masks the divergence; if only `_new_counter()` initializes it, rolled-forward legacy buckets never gain the key.

**Why:** Fresh vs. rolled-forward buckets silently diverge, producing inconsistent `pr_stats.json` output depending on when a bucket was first created.
