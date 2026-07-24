---
id: 0550
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:39:28.153779+00:00
status: active
corroborations: 1
supersedes: 0494,0495,0496,0497,0498,0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522,0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539
---

# Verify a file exists via git ls-files before planning an edit to it

Before adding a plan task that edits a specific file, confirm the file exists via `git ls-files <path>`.

Example: `git ls-files src/shared_prompt_prefix.py` returning empty means the file never existed — update the plan before implementation starts.

**Why:** Planning tasks against nonexistent files wastes implementation work and causes confusing "file not found" failures mid-execution.
