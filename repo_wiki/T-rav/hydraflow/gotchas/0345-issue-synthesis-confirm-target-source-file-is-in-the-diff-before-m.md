---
id: 0345
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T17:02:49.508270+00:00
status: active
corroborations: 1
supersedes: 0327,0328,0329,0330,0331,0332,0333,0334,0335,0336
---

# Confirm target source file is in the diff before merging a PR

Before merging, confirm the target source file appears in `git diff --name-only origin/main`.

Example: a PR closing an issue shows only `docs/` and `tests/` changed in `git diff --name-only`, while `src/makefile_scaffold.py` has 0 changes (issue #7644).

**Why:** Tests can pass against stubs or unchanged code; a green CI with no implementation changes ships dead-end work that silently does nothing.
