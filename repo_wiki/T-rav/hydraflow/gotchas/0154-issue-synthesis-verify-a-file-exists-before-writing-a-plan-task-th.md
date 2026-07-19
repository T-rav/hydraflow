---
id: 0154
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:23:52.949956+00:00
status: active
corroborations: 1
supersedes: 0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145
---

# Verify a file exists before writing a plan task that modifies it

Before adding a plan task that edits a specific file, confirm the file exists via `git ls-files <path>` or grep.

Example: `git ls-files src/shared_prompt_prefix.py` returns empty → file never existed; update the plan before implementation starts.

**Why:** Planning tasks against nonexistent files wastes implementation work and causes confusing "file not found" failures mid-execution.
