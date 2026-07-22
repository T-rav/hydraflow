---
id: 0335
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T15:33:18.682307+00:00
status: active
corroborations: 1
supersedes: 0317,0318,0319,0320,0321,0322,0323,0324,0325,0326
---

# Confirm target source file is in the diff before merging a PR

Before merging, confirm the target source file appears in `git diff --name-only origin/main`.

Example: a PR closing an issue shows only `docs/` and `tests/` changed in `git diff --name-only`, while `src/makefile_scaffold.py` has 0 changes (issue #7644).

**Why:** Tests can pass against stubs or unchanged code; a green CI with no implementation changes ships dead-end work that silently does nothing.
