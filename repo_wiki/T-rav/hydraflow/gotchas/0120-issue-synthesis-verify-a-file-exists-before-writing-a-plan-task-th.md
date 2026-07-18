---
id: 0120
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:54:44.599625+00:00
status: active
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
---

# Verify a file exists before writing a plan task that modifies it

Before adding a plan task that edits a specific file, confirm the file exists via `git ls-files <path>` or grep.

Example: `git ls-files src/shared_prompt_prefix.py` returns empty → file never existed; update the plan before implementation starts.

**Why:** Planning tasks against nonexistent files wastes implementation work and causes confusing "file not found" failures mid-execution.
