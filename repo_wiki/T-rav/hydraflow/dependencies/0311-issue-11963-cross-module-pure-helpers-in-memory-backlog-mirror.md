---
id: 0311
topic: dependencies
source_issue: 11963
source_phase: plan
created_at: 2026-09-01T09:53:18.676864+00:00
status: active
corroborations: 1
---

# Cross-module pure helpers in memory_backlog_mirror must be public

Pure helpers in `memory_backlog_mirror.py` that are consumed by `memory_backlog_loop.py` must be public (no `_` prefix), e.g. `find_citing_issue(summaries, entry, *, repo_relative_path) -> int | None`.

- Private (`_`-prefixed) functions can't be imported across modules without violating convention.
- Keep the matcher pure: takes summaries + entry, returns issue number or `None`, no I/O.

**Why:** Cross-module private imports break the module boundary contract and make the dependency graph harder to reason about.
