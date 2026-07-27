---
id: 0624
topic: patterns
source_issue: 10655
source_phase: plan
created_at: 2026-07-26T16:28:39.816286+00:00
status: superseded
corroborations: 1
superseded_by: 0666
---

# Gate wiki anchor liveness via AST symbols from wiki_rot_citations

When auditing wiki content for completeness, validate that anchors (backticked code spans naming symbols/paths) reference live code by checking against the symbol index from `wiki_rot_citations.py`. Use the public cached accessor, not the private `_collect_defined_symbols`. Build the index once per run, not per anchor.
- Without the live-code gate, 156/356 `left_on_primary` predecessors show zero representation — most are false positives.
**Why:** Stale anchors referencing deleted symbols produce noise that causes the entire audit report to be ignored.
