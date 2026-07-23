---
id: 0307
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T09:42:21.680184+00:00
status: superseded
corroborations: 1
supersedes: 0296,0297,0298,0299,0300,0301
superseded_by: 0310
---

# Confirm target source file is in the diff before merging

Before merging, confirm the target source file appears in `git diff --name-only origin/main`.

Example: a PR closing an issue shows only `docs/` and `tests/` changed in `git diff --name-only`, while `src/makefile_scaffold.py` has 0 changes (issue #7644).

**Why:** Tests can pass against stubs or unchanged code; a green CI with no implementation changes ships dead-end work that silently does nothing.
