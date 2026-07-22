---
id: 0298
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T08:12:52.209896+00:00
status: active
corroborations: 1
supersedes: 0288,0289,0290,0291,0292,0293
---

# Verify a file exists before writing a plan task that edits it

Before adding a plan task that edits a specific file, confirm the file exists via `git ls-files <path>`.

Example: `git ls-files src/shared_prompt_prefix.py` returning empty means the file never existed — update the plan before implementation starts.

**Why:** Planning tasks against nonexistent files wastes implementation work and causes confusing "file not found" failures mid-execution.
