---
id: 1186
topic: gotchas
source_issue: 10754
source_phase: plan
created_at: 2026-07-27T23:21:47.785777+00:00
status: active
corroborations: 1
---

# Rot-detector tool extraction: imperative position or .py suffix only

When adding tool-reference extraction rules to `src/wiki_rot_citations.py`, restrict grammar to imperative position or `.py` suffix tokens only.

Example: "Run `some_missing_tool`" extracts; a backticked class name mid-paragraph does not. If the corpus scan surfaces other dead tools, file `hydraflow-find` issues rather than widening the rule.

**Why:** A loose extractor flags every backticked snake_case token across ~3000 wiki entries, flooding the report with false positives and burying real rot.
