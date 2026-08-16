---
id: 3287
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T06:16:48.286080+00:00
status: active
corroborations: 1
supersedes: 3154
---

# Counter shape has two writers — change _new_counter and _accumulate

Any key added to `_new_counter()` must also be added to `_accumulate_counter()` in `src/prompt_telemetry.py` — both write the aggregate counter dict shape.

Example: If only `_accumulate_counter()` sums a new key, fresh buckets (via `_new_counter()`) lack it and `.get(k, 0)` masks the divergence; if only `_new_counter()` initializes it, rolled-forward legacy buckets never gain the key. See also: [patterns] — Roll forward legacy buckets.

**Why:** Fresh vs. rolled-forward buckets silently diverge, producing inconsistent `pr_stats.json` output depending on when a bucket was first created.
