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

In `src/escape_ledger_loop.py`, `eligible_findings` originally built `[*low_confidence_rows, *aging_rows]`; `_auto_diagnose` truncates `eligible[:max_diagnoses]` by index, and `apply_ask_budget` truncates `findings[:max_per_tick]` the same way. Fixed within the same PR by interleaving the two reason-groups round-robin (`itertools.zip_longest`) before either cap runs — `eligible_findings` no longer plain-concatenates.

**Why:** Static concatenation order lets one category permanently starve the other once its backlog reaches the cap — the root mechanism behind the #11126→#11176 issue family; moving the cap boundary only relocates the threshold. Applies to any future worklist that adds a second reason-group ahead of an existing capped list.
