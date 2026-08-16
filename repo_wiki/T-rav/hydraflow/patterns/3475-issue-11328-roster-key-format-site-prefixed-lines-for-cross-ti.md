---
id: 3475
topic: patterns
source_issue: 11328
source_phase: plan
created_at: 2026-08-16T09:56:55.839290+00:00
status: superseded
corroborations: 1
superseded_by: 3620
---

# Roster key format: site-prefixed lines for cross-tick idempotency

Use `- <site> — <title>` as the roster line in `find_class_key.py`, where `site` is a keyword-only `file:line` arg. Keep bare `- <title>` lines as fallback for pre-existing bodies.

- Re-offering a rostered site under different wording leaves the body byte-identical with no comment.
- Legacy bodies without site lines still dedupe via the title-only fallback.

**Why:** Title-only keys break dedup when the same site is re-offered under different wording, producing duplicate lines or a per-tick comment storm.
