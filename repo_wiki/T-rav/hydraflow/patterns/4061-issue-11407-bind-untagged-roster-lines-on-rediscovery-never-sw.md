---
id: 4061
topic: patterns
source_issue: 11407
source_phase: plan
created_at: 2026-08-18T02:53:10.561457+00:00
status: stale
corroborations: 1
stale_reason: source issue #11407 closed
---

# Bind untagged roster lines on rediscovery, never swallow

When `_append_site` in `src/find_class_key.py` finds an incoming `site` that differs from `title` and the roster has a bare `- {title}` line (no `(site: …)` tag), rewrite that line via `_site_line(title, site)` and return. Keep the no-op only when `site is None` or `site == title`.

- Tagged line with matching site identifier → still hits `effective_site` branch.
- Bare line + explicit different site → bind (one rewrite).
- Bare line + no site → no-op (pre-#11328 behavior).

**Why:** Swallowing every `title in existing_sites` match silently drops genuinely new sites and causes the fold to falsely report success.
