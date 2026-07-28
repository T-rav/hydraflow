---
id: 0246
topic: architecture
source_issue: 10754
source_phase: plan
created_at: 2026-07-27T23:21:47.785737+00:00
status: active
corroborations: 1
---

# Cross-module _-prefixed imports banned; expose public functions

When logic in a `src/` module needs reuse elsewhere, expose it as a public function — cross-module imports of `_`-prefixed names are banned.

Example: `src/wiki_anchor_gate.py` exposes `extract_repo_anchors(text, *, config_fields)` and re-implements `has_repo_anchor` on top of it, so `wiki_lesson_coverage.py` can call it directly.

**Why:** Private functions have no stability contract; importing them across modules couples consumers to internal layout and breaks when internals move.
