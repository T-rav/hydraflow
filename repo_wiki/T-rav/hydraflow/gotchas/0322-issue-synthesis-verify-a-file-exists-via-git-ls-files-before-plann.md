---
id: 0322
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T13:38:34.195618+00:00
status: active
corroborations: 1
supersedes: 0310,0310,0311,0311,0312,0312,0313,0314,0315,0316
---

# Verify a file exists via git ls-files before planning an edit to it

Before adding a plan task that edits a specific file, confirm the file exists via `git ls-files <path>`.

Example: `git ls-files src/shared_prompt_prefix.py` returning empty means the file never existed — update the plan before implementation starts.

**Why:** Planning tasks against nonexistent files wastes implementation work and causes confusing "file not found" failures mid-execution.
