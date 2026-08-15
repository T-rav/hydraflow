---
id: 2178
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T23:28:16.658851+00:00
status: superseded
corroborations: 1
supersedes: 2065
superseded_by: 2294
---

# Use %x01 not %x1e as git log sentinel in check_console_conformance.py

Use `%x01` as the commit-boundary marker in `git log --format` for `scripts/check_console_conformance.py`. Avoid `%x1e` — Python's `str.splitlines()` treats U+001E (Record Separator) as a line terminator and silently splits on it, corrupting per-commit grouping.

Example: `--format='%H%x01%s'` then `output.split("\n")` is safe; `%x1e` fragments each commit line.

**Why:** The classifier depends on one line per change; an invisible terminator breaks parsing and silently drops violations from check #6.
