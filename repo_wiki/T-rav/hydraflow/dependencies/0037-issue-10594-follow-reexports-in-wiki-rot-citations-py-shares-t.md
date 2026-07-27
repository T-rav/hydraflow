---
id: 0037
topic: dependencies
source_issue: 10594
source_phase: plan
created_at: 2026-07-26T04:15:06.679663+00:00
status: superseded
corroborations: 1
superseded_by: 0043
---

# _follow_reexports in wiki_rot_citations.py shares the symbol collector

`_follow_reexports` in `src/wiki_rot_citations.py` calls the same `_collect_defined_symbols` helper used by `verify_cite_ast`, so any widening of that helper (e.g. adding assignment-binding support) automatically applies to depth-1 re-exported constants via `from .x import` in `__init__.py` — no separate fix needed.

**Why:** avoids duplicating symbol-resolution logic across the direct-cite and re-export verification paths.
