---
id: 0955
topic: patterns
source_issue: 10817
source_phase: plan
created_at: 2026-07-31T01:28:07.214985+00:00
status: active
corroborations: 1
---

# Use startswith on normalized posix paths, not substring `in`, for scope checks

When checking whether a changed path falls inside a maintenance loop's write scope, use `path.startswith(scope)` on normalized lowercase posix paths — never `scope in path` (substring match).

Example: `src/audit/docs_wiki.py` contains the substring `docs/wiki` but is NOT inside `docs/wiki/` scope. Substring matching would falsely exclude it.

**Why:** Stratify's `in` operator admits paths that merely contain the scope string as a substring, re-opening the escape hole the scope table was built to close.
