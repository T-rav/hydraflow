---
id: 2829
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T11:44:51.783292+00:00
status: superseded
corroborations: 1
supersedes: 2700
superseded_by: 2956
---

# verify_cite_ast changes ripple into _shipped_claim_corroborated

`verify_cite_ast` in `src/wiki_rot_citations.py` is consumed by more than the cite-checking path — `_shipped_claim_corroborated` also calls it to validate shipped-feature claims. Check both callers before merging a scope change.

Example: Widening the symbol set (e.g. to admit constants) makes more claims corroborate too.

**Why:** A scope change intended for one caller silently changes behavior for a second, unrelated verification path.
