---
id: 0084
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T04:21:57.759465+00:00
status: active
corroborations: 1
supersedes: 0076
---

# _follow_reexports reuses the same _collect_defined_symbols helper

`_follow_reexports` in `src/wiki_rot_citations.py` calls the same `_collect_defined_symbols` helper used by `verify_cite_ast`, so any widening of that helper automatically applies to depth-1 re-exported constants via `from .x import` in `__init__.py`.

Example: Adding assignment-binding support to `_collect_defined_symbols` fixes both direct-cite verification and re-export verification in one change. See also: dependencies — ADR drift: drop src/ prefix, don't add :Symbol, for bare citations.

**Why:** Avoids duplicating symbol-resolution logic across the direct-cite and re-export verification paths.
