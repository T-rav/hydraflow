---
id: 0342
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T17:02:49.506704+00:00
status: superseded
corroborations: 1
supersedes: 0327,0328,0329,0330,0331,0332,0333,0334,0335,0336
superseded_by: 0348
---

# Verify a file exists via git ls-files before planning an edit to it

Before adding a plan task that edits a specific file, confirm the file exists via `git ls-files <path>`.

Example: `git ls-files src/shared_prompt_prefix.py` returning empty means the file never existed — update the plan before implementation starts.

**Why:** Planning tasks against nonexistent files wastes implementation work and causes confusing "file not found" failures mid-execution.
