---
id: 0222
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:45:05.795282+00:00
status: active
corroborations: 1
supersedes: 0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213
---

# Verify a file exists before writing a plan task that modifies it

Before adding a plan task that edits a specific file, confirm the file exists via `git ls-files <path>` or grep.

Example: `git ls-files src/shared_prompt_prefix.py` returns empty → file never existed; update the plan before implementation starts.

**Why:** Planning tasks against nonexistent files wastes implementation work and causes confusing "file not found" failures mid-execution.
