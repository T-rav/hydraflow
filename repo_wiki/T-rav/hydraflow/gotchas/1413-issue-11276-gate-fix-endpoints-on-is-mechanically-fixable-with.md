---
id: 1413
topic: gotchas
source_issue: 11276
source_phase: plan
created_at: 2026-08-15T21:04:18.934672+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Gate fix endpoints on is_mechanically_fixable() with source citation

Fix endpoints must call `is_mechanically_fixable()` and reject non-members of `MECHANICALLY_FIXABLE_CHECK_IDS` with a 422 that embeds the check's `source` citation. Build the check context via `registry.get` + `context.build(target_path)` so the citation is available.

**Why:** Without the `source` citation in the error payload, users can't trace why a check was rejected or where the fixability rule originates.
