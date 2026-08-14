---
id: 1793
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T12:50:03.970314+00:00
status: active
corroborations: 1
supersedes: 1697
---

# Surfacing reasons are independent one-shot budgets

Keep `low-confidence` and `aging` surfacing reasons answerable only by their own field. Never let an encoding auto-answer a confidence question.

Example: `src/escape_ledger_loop.py:_surfacing_answered` answers `low-confidence` solely on `attribution_confidence != "low"`. The `surfacing_fingerprint` docstring documents the two-budget split.

**Why:** Cross-answering destroys the human-label signal and pre-empts the row's legitimate later `aging` surface.
