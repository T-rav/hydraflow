---
id: 3797
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T15:30:56.042373+00:00
status: superseded
corroborations: 1
supersedes: 3652
superseded_by: 3944
---

# verify_cite_ast changes ripple into _shipped_claim_corroborated

`verify_cite_ast` in `src/wiki_rot_citations.py` is consumed by more than the cite-checking path — `_shipped_claim_corroborated` also calls it to validate shipped-feature claims. Check both callers before merging a scope change.

Example: Widening the symbol set (e.g. to admit constants) makes more claims corroborate too.

**Why:** A scope change intended for one caller silently changes behavior for a second, unrelated verification path.
