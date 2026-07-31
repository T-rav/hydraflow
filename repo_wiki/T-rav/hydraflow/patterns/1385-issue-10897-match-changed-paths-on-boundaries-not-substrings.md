---
id: 1385
topic: patterns
source_issue: 10897
source_phase: plan
created_at: 2026-07-31T12:53:03.086166+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Match changed paths on / boundaries, not substrings

Scope membership checks in `paths_within_maintenance_scope(subject, paths)` use repo-root-relative paths matched on `/` boundaries. `docs/arch-notes/x` does NOT fall within a `docs/arch` scope because the character after `docs/arch` is `-`, not `/`. **Why:** Substring matching would let any path containing the scope string as a textual prefix escape audit sampling.
