---
id: 0144
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:54:44.608510+00:00
status: superseded
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
superseded_by: 0146
---

# Verify implementation files are in the diff before merging

Before merging, confirm the target source file appears in `git diff --name-only origin/main`.

Example: PR closes #7644 but `git diff --name-only` shows only `docs/` and `tests/` — `src/makefile_scaffold.py` has 0 changes.

**Why:** Tests can pass against stubs or unchanged code; a green CI with no implementation changes ships dead-end work that silently does nothing.
