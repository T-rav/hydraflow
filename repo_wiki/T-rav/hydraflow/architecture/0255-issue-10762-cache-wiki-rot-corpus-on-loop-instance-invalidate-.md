---
id: 0255
topic: architecture
source_issue: 10762
source_phase: plan
created_at: 2026-07-28T00:37:27.487537+00:00
status: active
corroborations: 1
---

# Cache wiki-rot corpus on loop instance, invalidate per tick

Rule: The bare-cite corpus (~22 MB of Python) must be cached on the `WikiRotDetectorLoop` instance and invalidated at the top of `_do_work`, never at module level. Build lazily via `rglob` over the tree, not a hardcoded file list. Two ticks on the same instance must rebuild.

**Why:** Module-level caches persist across ticks, causing stale resolution against an updated checkout.
