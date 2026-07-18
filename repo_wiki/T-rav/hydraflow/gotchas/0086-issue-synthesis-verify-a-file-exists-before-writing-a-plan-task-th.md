---
id: 0086
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T19:10:32.483465+00:00
status: active
corroborations: 1
supersedes: 0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077
---

# Verify a file exists before writing a plan task that modifies it

Before adding a plan task that edits a specific file, confirm the file exists via `git ls-files <path>` or grep.

Example: `git ls-files src/shared_prompt_prefix.py` returns empty → file never existed; update the plan before implementation starts.

**Why:** Planning tasks against nonexistent files wastes implementation work and causes confusing "file not found" failures mid-execution.
