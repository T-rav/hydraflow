---
id: 0043
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:17:41.778156+00:00
status: active
corroborations: 1
supersedes: 0032,0033,0034,0035,0036,0037
---

# _follow_reexports in wiki_rot_citations.py shares the symbol collector

`_follow_reexports` in `src/wiki_rot_citations.py` calls the same `_collect_defined_symbols` helper used by `verify_cite_ast`, so any widening of that helper automatically applies to depth-1 re-exported constants via `from .x import` in `__init__.py`.

Example: adding assignment-binding support to `_collect_defined_symbols` fixes both direct-cite verification and re-exported constant detection in one change — no separate fix needed.

**Why:** Avoids duplicating symbol-resolution logic across the direct-cite and re-export verification paths.
