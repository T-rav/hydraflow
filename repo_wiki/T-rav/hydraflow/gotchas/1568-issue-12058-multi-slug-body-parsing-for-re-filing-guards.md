---
id: 1568
topic: gotchas
source_issue: 12058
source_phase: plan
created_at: 2026-09-02T22:01:19.186903+00:00
status: active
corroborations: 1
---

# Multi-slug body parsing for re-filing guards

The `filed_slugs` guard must resolve every slug named in an issue body's mirror-path lines, not just the first; this prevents duplicate summaries when an overflow issue lists multiple over-cap entries.

Example: An issue body with three `filed-mirror: docs/wiki/memory-feedback/foo.md` lines must resolve to all three slugs, deduped and ordered.

**Why:** Single-slug parsing misses duplicates; a fresh clone re-files if any slug is missed.
