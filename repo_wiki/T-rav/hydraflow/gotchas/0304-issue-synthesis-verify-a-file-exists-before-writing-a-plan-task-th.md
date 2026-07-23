---
id: 0304
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T09:42:21.676449+00:00
status: superseded
corroborations: 1
supersedes: 0296,0297,0298,0299,0300,0301
superseded_by: 0310
---

# Verify a file exists before writing a plan task that edits it

Before adding a plan task that edits a specific file, confirm the file exists via `git ls-files <path>`.

Example: `git ls-files src/shared_prompt_prefix.py` returning empty means the file never existed — update the plan before implementation starts.

**Why:** Planning tasks against nonexistent files wastes implementation work and causes confusing "file not found" failures mid-execution.
