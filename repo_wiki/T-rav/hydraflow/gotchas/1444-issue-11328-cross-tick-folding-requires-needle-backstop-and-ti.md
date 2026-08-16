---
id: 1444
topic: gotchas
source_issue: 11328
source_phase: plan
created_at: 2026-08-16T09:56:55.839267+00:00
status: active
corroborations: 1
---

# Cross-tick folding requires needle backstop AND title-affinity floor

Folding in `find_class_key.py` must require BOTH a shared needle token (title or body) AND title-affinity ≥ `CLASS_MARKER_TITLE_FLOOR`. Marker equality alone must never fold.

- A digest collision whose candidate title shares no token with the matched issue does not fold, even if its body contains a needle token.
- A same-class sibling with a rewritten title still folds when both conditions hold.

**Why:** Digest collisions produce false folds that merge unrelated issues; the dual condition closes the hole while preserving real sibling folds.
