---
id: 3329
topic: patterns
source_issue: 11298
source_phase: plan
created_at: 2026-08-16T05:49:45.238826+00:00
status: superseded
corroborations: 1
superseded_by: 3465
---

# Cache hit rate denominator includes cache_creation in token_report

Compute cache hit rate as `cache_read / (input + cache_creation + cache_read)`. A row with `input=2, cache_creation=17458, cache_read=67087` reports ~0.79, not 1.0. Estimate-only buckets report a null cache hit rate with `unit == "estimate"`.

**Why:** Omitting `cache_creation` from the denominator inflates hit rate to 1.0 whenever any cache read occurs, hiding cache-miss costs in `src/token_report.py` diagnostics.
