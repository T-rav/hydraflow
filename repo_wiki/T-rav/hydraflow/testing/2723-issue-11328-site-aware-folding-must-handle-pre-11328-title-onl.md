---
id: 2723
topic: testing
source_issue: 11328
source_phase: review
created_at: 2026-08-16T12:27:43.693208+00:00
status: active
corroborations: 1
---

# Site-aware folding must handle pre-#11328 title-only roster lines

When adding site tags to class-issue roster lines, also check title equality against existing untagged lines. `extract_folded_sites` in `src/find_class_key.py` returns the legacy line's title text as key, but the site-aware lookup checks the site identifier — these never match for pre-#11328 issues, so the first site-aware re-discovery appends a duplicate roster line.

- Seed idempotency tests from a title-only body, not just already-tagged fixtures.
- Pre-#11328 open class issues all have title-only roster lines.

**Why:** Without title-equality fallback, every live legacy class issue gets a duplicate roster line and spurious comment on first site-aware discovery.
