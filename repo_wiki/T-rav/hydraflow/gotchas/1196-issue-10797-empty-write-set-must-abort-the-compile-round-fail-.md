---
id: 1196
topic: gotchas
source_issue: 10797
source_phase: plan
created_at: 2026-07-28T09:50:07.998818+00:00
status: active
corroborations: 1
---

# Empty write set must abort the compile round fail-closed

When `partition_noop_synthesis` returns an empty write tuple, `_flow_synthesize` (`src/wiki_compiler.py:853`) must stop the round and leave every input `active` — do not proceed to supersede.

- A drop-only batch (nothing to write) aborts with all inputs active.
- `_flow_validate` writes/supersedes only partitioned subsets, resolving `superseded_by` against just retired actives.

**Why:** Proceeding to supersede with no replacement writes would silently drop facts from the topic without a successor, violating the no-data-loss invariant.
