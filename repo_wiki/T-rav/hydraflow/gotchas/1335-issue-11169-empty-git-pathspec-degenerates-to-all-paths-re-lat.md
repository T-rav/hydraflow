---
id: 1335
topic: gotchas
source_issue: 11169
source_phase: plan
created_at: 2026-08-14T19:43:33.955265+00:00
status: active
corroborations: 1
---

# Empty git pathspec degenerates to all-paths, re-latching immutability checks

When `git ls-tree` at the merge-base returns zero decision records (e.g., a fresh branch point under `agents/console/decisions/`), passing an empty pathspec to `git log <mb>..HEAD` silently matches every file in the repo.

In `scripts/check_console_conformance.py`, guard against this: if the record set is empty, skip check #6 rather than passing an empty pathspec.

**Why:** The empty-set case reintroduces the exact latching bug the scoping fix targets — a degenerate pathspec re-flags unrelated commits and turns one merged amendment into a permanent red.
