---
id: 0251
topic: architecture
source_issue: 10757
source_phase: plan
created_at: 2026-07-28T00:08:58.218736+00:00
status: active
corroborations: 1
---

# Expose _-prefixed anchor regexes via public API, never import privately

Rule: `src/wiki_anchor_gate.py` keeps its regex helpers `_`-prefixed; cross-module consumers must call the public `repo_anchor_tokens(text, *, config_fields=None) -> frozenset[str]` instead of importing private internals. `has_repo_anchor` is re-expressed on this public API with identical semantics.

Example: `src/wiki_lesson_coverage.py` calls `repo_anchor_tokens(predecessor_body)` to get `.py` paths, ADR refs, CamelCase class names, and config fields — never reaches into `_`-prefixed helpers.

**Why:** Direct import of `_`-prefixed regexes couples consumers to implementation details and breaks the module boundary the gate enforces.
