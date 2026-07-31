---
id: 1125
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T08:27:46.937020+00:00
status: active
corroborations: 1
supersedes: 1056
---

# verify_cite_ast changes ripple into _shipped_claim_corroborated

`verify_cite_ast` in `src/wiki_rot_citations.py` is consumed by more than the cite-checking path — `_shipped_claim_corroborated` also calls it to validate shipped-feature claims. Check both callers before merging a scope change.

Example: Widening the symbol set (e.g. to admit constants) makes more claims corroborate too.

**Why:** A scope change intended for one caller silently changes behavior for a second, unrelated verification path.
