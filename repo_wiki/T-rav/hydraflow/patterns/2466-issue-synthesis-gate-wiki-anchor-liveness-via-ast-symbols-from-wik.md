---
id: 2466
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T06:55:23.411842+00:00
status: superseded
corroborations: 1
supersedes: 2346
superseded_by: 2589
---

# Gate wiki anchor liveness via AST symbols from wiki_rot_citations

When auditing wiki content for completeness, validate that anchors (backticked code spans naming symbols/paths) reference live code by checking against the symbol index from `wiki_rot_citations.py`. Use the public cached accessor, not `_collect_defined_symbols`. Build the index once per run, not per anchor.

Example: Without the live-code gate, 156/356 `left_on_primary` predecessors show zero representation — most are false positives.

**Why:** Stale anchors referencing deleted symbols produce noise that causes the entire audit report to be ignored.
