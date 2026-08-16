---
id: 2841
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T11:44:51.874368+00:00
status: superseded
corroborations: 1
supersedes: 2712
superseded_by: 2968
---

# Gate wiki anchor liveness via AST symbols from wiki_rot_citations

When auditing wiki content for completeness, validate that anchors (backticked code spans naming symbols/paths) reference live code by checking against the symbol index from `wiki_rot_citations.py`. Use the public cached accessor, not `_collect_defined_symbols`. Build the index once per run, not per anchor.

Example: Without the live-code gate, 156/356 `left_on_primary` predecessors show zero representation — most are false positives.

**Why:** Stale anchors referencing deleted symbols produce noise that causes the entire audit report to be ignored.
