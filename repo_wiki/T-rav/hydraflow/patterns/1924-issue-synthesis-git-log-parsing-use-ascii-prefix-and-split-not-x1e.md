---
id: 1924
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T14:29:27.018473+00:00
status: active
corroborations: 1
supersedes: 1826
---

# Git log parsing: use ASCII prefix and split, not \x1e delimiter

Parse `git log` subprocess output with an ASCII record prefix and `split("\n")`, not a `\x1e` delimiter plus `splitlines()`.

Example: In `arch/runner.py`'s `_git_log_adr_authorship(repo_root)` adapter, use a literal `--format` string with an ASCII separator to delimit records.

**Why:** The `\x1e`/`splitlines()` approach mishandles record boundaries on this repo's git output; literal format strings are the required convention.
