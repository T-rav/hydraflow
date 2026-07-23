---
id: 0301
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T08:12:52.211264+00:00
status: superseded
corroborations: 1
supersedes: 0288,0289,0290,0291,0292,0293
superseded_by: 0302
---

# Confirm target source file is in the diff before merging

Before merging, confirm the target source file appears in `git diff --name-only origin/main`.

Example: a PR closing an issue shows only `docs/` and `tests/` changed in `git diff --name-only`, while `src/makefile_scaffold.py` has 0 changes (issue #7644).

**Why:** Tests can pass against stubs or unchanged code; a green CI with no implementation changes ships dead-end work that silently does nothing.
