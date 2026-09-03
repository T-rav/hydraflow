---
id: 1571
topic: gotchas
source_issue: 12058
source_phase: plan
created_at: 2026-09-02T22:01:19.186934+00:00
status: active
corroborations: 1
---

# Dedup state persistence via board-side guards

`.hydraflow/dedup/` is gitignored, so key releases are local runtime state. Board-side guards (multi-slug body parsing) survive re-clone; the next clone reads the summary issue and heals all rows pointing at it without re-filing (per ADR-0112 per-issue clones).

Example: After clone, if an open summary lists all over-cap entry slugs, `filed_slugs` sees them in the body and files zero duplicates.

**Why:** Git-persisted dedup keys don't survive per-issue clones; guards on the board's API state do.
