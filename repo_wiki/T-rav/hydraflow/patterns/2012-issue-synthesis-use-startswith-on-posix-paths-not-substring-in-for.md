---
id: 2012
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T18:39:31.749778+00:00
status: superseded
corroborations: 1
supersedes: 1904
superseded_by: 2128
---

# Use startswith on posix paths, not substring in, for scope checks

When checking whether a changed path falls inside a maintenance loop's write scope, use `path.startswith(scope)` on normalized lowercase posix paths — never `scope in path` (substring match).

Example: `src/audit/docs_wiki.py` contains the substring `docs/wiki` but is NOT inside `docs/wiki/` scope. Substring matching would falsely exclude it. See also: [patterns] — Self-chore exclusion requires path corroboration.

**Why:** `in` operator admits paths that merely contain the scope string as a substring, re-opening the escape hole the scope table was built to close.
