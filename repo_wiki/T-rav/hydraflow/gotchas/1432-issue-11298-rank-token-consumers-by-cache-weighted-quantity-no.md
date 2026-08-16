---
id: 1432
topic: gotchas
source_issue: 11298
source_phase: plan
created_at: 2026-08-16T05:49:45.238811+00:00
status: active
corroborations: 1
---

# Rank token consumers by cache-weighted quantity, not raw totals

Rank issues by a cache-weighted quantity instead of raw token sums. In `src/token_report.py`, `weighted = input + output + 1.25*cache_creation + 0.1*cache_read` is published under the existing `tokens` wire key; the docstring must document this substitution.

**Why:** Raw totals treat cache reads as full-cost input, making cache-heavy loops look up to 10x more expensive than they are and distorting fleet cost decisions in the diagnostics cost tab.
