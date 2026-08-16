---
id: 3620
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T12:13:23.483659+00:00
status: superseded
corroborations: 1
supersedes: 3475
superseded_by: 3765
---

# Roster key format: site-prefixed lines for cross-tick idempotency

Use `- <site> — <title>` as the roster line in `find_class_key.py`, where `site` is a keyword-only `file:line` arg. Keep bare `- <title>` lines as fallback for pre-existing bodies.

Re-offering a rostered site under different wording leaves the body byte-identical with no comment. Legacy bodies without site lines still dedupe via the title-only fallback.

**Why:** Title-only keys break dedup when the same site is re-offered under different wording, producing duplicate lines or a per-tick comment storm.
