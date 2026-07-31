---
id: 0884
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T19:37:32.654363+00:00
status: superseded
corroborations: 1
supersedes: 0829
superseded_by: 0942
---

# Surfacing reasons are independent one-shot budgets

Keep `low-confidence` and `aging` surfacing reasons answerable only by their own field. Never let an encoding auto-answer a confidence question.

- `src/escape_ledger_loop.py:_surfacing_answered` answers `low-confidence` solely on `attribution_confidence != "low"`.
- The `surfacing_fingerprint` docstring documents the two-budget split.

**Why:** Cross-answering destroys the human-label signal and pre-empts the row's legitimate later `aging` surface.
