---
id: 1188
topic: gotchas
source_issue: 10758
source_phase: plan
created_at: 2026-07-27T23:48:31.703718+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Only status: active citations count as wiki representation

A predecessor cited exclusively by `status: stale` entries tiers as `orphaned`, not `represented`.

- Tiers: `represented` (all live anchors cited by active entries), `weak` (partial or dangling `[[wikilink]]`), `orphaned` (none).
- Verified case: zero `status: active` entries cite `_SHA_MARKER`, so `gotchas/0841` tiers `orphaned`.

**Why:** Stale entries are excluded from agent prompt injection; counting them as representation hides lessons that silently left the active corpus.
