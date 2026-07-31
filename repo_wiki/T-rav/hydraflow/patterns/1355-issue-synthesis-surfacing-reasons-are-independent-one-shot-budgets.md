---
id: 1355
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T14:16:20.856381+00:00
status: superseded
corroborations: 1
supersedes: 1281
superseded_by: 1434
---

# Surfacing reasons are independent one-shot budgets

Keep `low-confidence` and `aging` surfacing reasons answerable only by their own field. Never let an encoding auto-answer a confidence question.

Example: `src/escape_ledger_loop.py:_surfacing_answered` answers `low-confidence` solely on `attribution_confidence != "low"`. The `surfacing_fingerprint` docstring documents the two-budget split.

**Why:** Cross-answering destroys the human-label signal and pre-empts the row's legitimate later `aging` surface.
