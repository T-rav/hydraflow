---
id: 0581
topic: patterns
source_issue: 10594
source_phase: plan
created_at: 2026-07-26T04:15:06.679684+00:00
status: superseded
corroborations: 1
superseded_by: 0612
---

# verify_cite_ast changes ripple into _shipped_claim_corroborated

`verify_cite_ast` in `src/wiki_rot_citations.py` is consumed by more than the cite-checking path — `_shipped_claim_corroborated` also calls it to validate shipped-feature claims. Widening the symbol set (e.g. to admit constants) makes more claims corroborate too, not just more cites verify.

**Why:** a scope change intended for one caller silently changes behavior for a second, unrelated verification path — check both before merging.
