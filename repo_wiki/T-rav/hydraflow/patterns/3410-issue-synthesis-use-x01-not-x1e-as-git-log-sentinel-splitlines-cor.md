---
id: 3410
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T08:05:57.881743+00:00
status: active
corroborations: 1
supersedes: 3273
---

# Use %x01 not %x1e as git log sentinel — splitlines corrupts records

Use `%x01` (not `%x1e`) as the commit-boundary marker in `git log --format`, then parse with `split("\n")` — never `splitlines()`.

Example: `--format='%H%x01%s'` in both `arch/runner.py:_git_log_adr_authorship` and `scripts/check_console_conformance.py` check #6. Python's `str.splitlines()` treats U+001E (Record Separator) as a line terminator, silently fragmenting per-commit records.

**Why:** The classifier depends on one line per change; an invisible U+001E terminator breaks parsing and silently drops violations from check #6.
