---
id: 0333
topic: architecture
source_issue: 11169
source_phase: plan
created_at: 2026-08-14T19:43:33.955221+00:00
status: active
corroborations: 1
---

# Git pathspec with trailing */ matches directories only, not blobs

Drop the trailing `*/` from directory pathspecs in `git log` and `git ls-tree` calls within `scripts/check_console_conformance.py`. `agents/console/decisions/*/` matches directories only, making the entire `check_git=True` branch (lines 117-136) dead code — the check never fires.

- Wrong: `agents/console/decisions/*/`
- Right: `agents/console/decisions` (recursive, matches blobs)

**Why:** The immutability check silently never executes, producing a vacuous green identical to the #11110 failure mode.
