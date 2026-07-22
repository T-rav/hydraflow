---
id: 0287
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T04:10:53.482045+00:00
status: active
corroborations: 1
supersedes: 0248,0249,0250,0251,0252,0253,0254,0255,0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281
---

# Confirm target source file is in the diff before merging

Rule: Before merging, confirm the target source file appears in `git diff --name-only origin/main`.

Example: a PR closing an issue shows only `docs/` and `tests/` changed in `git diff --name-only`, while `src/makefile_scaffold.py` has 0 changes (issue #7644).

**Why:** Tests can pass against stubs or unchanged code; a green CI with no implementation changes ships dead-end work that silently does nothing.
