---
id: 0756
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T11:16:04.370329+00:00
status: superseded
corroborations: 1
supersedes: 0699
superseded_by: 0812
---

# verify_cite_ast changes ripple into _shipped_claim_corroborated

`verify_cite_ast` in `src/wiki_rot_citations.py` is consumed by more than the cite-checking path — `_shipped_claim_corroborated` also calls it to validate shipped-feature claims. Widening the symbol set (e.g. to admit constants) makes more claims corroborate too.

Example: Check both callers before merging a scope change to `verify_cite_ast`.

**Why:** A scope change intended for one caller silently changes behavior for a second, unrelated verification path.
