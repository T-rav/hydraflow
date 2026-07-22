---
id: 0256
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:39:19.021130+00:00
status: superseded
corroborations: 1
supersedes: 0214,0215,0216,0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247
superseded_by: 0282
---

# Verify a file exists before writing a plan task that modifies it

Before adding a plan task that edits a specific file, confirm the file exists via `git ls-files <path>` or grep.

Example: `git ls-files src/shared_prompt_prefix.py` returns empty → file never existed; update the plan before implementation starts.

**Why:** Planning tasks against nonexistent files wastes implementation work and causes confusing "file not found" failures mid-execution.
