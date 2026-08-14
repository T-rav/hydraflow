---
id: 1551
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:30:39.180229+00:00
status: superseded
corroborations: 1
supersedes: 1467
superseded_by: 1636
---

# Git log parsing: use ASCII prefix and split("\n"), not \x1e

Parse `git log` subprocess output with an ASCII record prefix and `split("\n")`, not a `\x1e` delimiter plus `splitlines()`.

Example: In `arch/runner.py`'s `_git_log_adr_authorship(repo_root)` adapter, use a literal `--format` string with an ASCII separator to delimit records.

**Why:** The `\x1e`/`splitlines()` approach mishandles record boundaries on this repo's git output; literal format strings are the required convention.
