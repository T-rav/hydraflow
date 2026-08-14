---
id: 1840
topic: patterns
source_issue: 11126
source_phase: plan
created_at: 2026-08-14T11:53:15.165951+00:00
status: active
corroborations: 1
---

# diagnose() must return recorded terminal verdict, not INCONCLUSIVE

When re-diagnosing an escape that already has a terminal verdict (e.g., DISMISSED), `EscapeAutoDiagnoser.diagnose()` must return that recorded verdict — never `INCONCLUSIVE`.

- A dismissed row re-filed at a human on every tick was caused by `diagnose()` returning `INCONCLUSIVE` against its own docstring.
- Aging rows never mutate the ledger, so they re-fire forever without this fix.

**Why:** Without terminal verdicts staying terminal, widening auto-diagnose scope to all surfacing reasons creates an infinite re-firing loop that never converges.
