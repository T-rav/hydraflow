---
id: 1034
topic: gotchas
source_issue: 10561
source_phase: plan
created_at: 2026-07-25T23:57:26.301223+00:00
status: superseded
corroborations: 1
superseded_by: 1039
---

# Bound self-heal reclassification passes with a DedupStore one-shot fingerprint

For loops that re-scan and correct past output (like `EscapeLedgerLoop`'s stale-row reclassification), gate each row to at most one re-read ever using a `DedupStore` fingerprint like `reclassified:<id>`, and cap total git reads per tick via a config field (`escape_ledger_max_reclassify_per_tick`, default 5 in `src/config.py`). Never touch rows already at medium/high, and never write a corrected row unless it's strictly stronger than the one it supersedes — an adapter failure or empty `added_paths` (merge commit, shallow clone) must leave the row untouched, not downgrade it.

**Why:** an unbounded or repeatable self-heal pass turns into either an unbounded git-log workload per tick or a flapping classification if the adapter has a partial-failure mode.
