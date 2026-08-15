---
id: 2294
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T01:03:09.990566+00:00
status: superseded
corroborations: 1
supersedes: 2178
superseded_by: 2414
---

# Use %x01 not %x1e as git log sentinel in check_console_conformance.py

Use `%x01` as the commit-boundary marker in `git log --format` for `scripts/check_console_conformance.py`. Avoid `%x1e` — Python's `str.splitlines()` treats U+001E (Record Separator) as a line terminator and silently splits on it, corrupting per-commit grouping.

Example: `--format='%H%x01%s'` then `output.split("\n")` is safe; `%x1e` fragments each commit line.

**Why:** The classifier depends on one line per change; an invisible terminator breaks parsing and silently drops violations from check #6.
