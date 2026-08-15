---
id: 1354
topic: gotchas
source_issue: 11176
source_phase: review
created_at: 2026-08-15T01:02:21.454109+00:00
status: active
corroborations: 1
---

# Concatenated worklist caps inherit ordering bias without fairness key

Apply a fairness key (interleave-by-reason or global age-sort) to any concatenated candidate list before a per-tick cap truncates it — both `eligible_findings` and `apply_ask_budget` must share the same ordering invariant.

In `src/escape_ledger_loop.py`, `eligible_findings` builds `[*low_confidence_rows, *aging_rows]`; `_auto_diagnose` truncates `eligible[:max_diagnoses]` by index, and `apply_ask_budget` truncates `findings[:max_per_tick]` the same way.

**Why:** Static concatenation order lets one category permanently starve the other once its backlog reaches the cap — the root mechanism behind the #11126→#11176 issue family; moving the cap boundary only relocates the threshold.
