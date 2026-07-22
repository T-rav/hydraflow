---
id: 0353
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T18:02:32.382406+00:00
status: active
corroborations: 1
supersedes: 0337,0338,0339,0340,0341,0342,0343,0344,0345,0346,0347
---

# Verify a file exists via git ls-files before planning an edit to it

Before adding a plan task that edits a specific file, confirm the file exists via `git ls-files <path>`.

Example: `git ls-files src/shared_prompt_prefix.py` returning empty means the file never existed — update the plan before implementation starts.

**Why:** Planning tasks against nonexistent files wastes implementation work and causes confusing "file not found" failures mid-execution.
