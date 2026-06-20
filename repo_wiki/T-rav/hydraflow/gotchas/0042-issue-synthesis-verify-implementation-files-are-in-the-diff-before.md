---
id: 0042
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.698658+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# Verify implementation files are in the diff before merging a feature PR

Before merging, confirm the target source file appears in `git diff --name-only origin/main`.

Example: PR closes #7644 but `git diff --name-only` shows only `docs/` and `tests/` — `src/makefile_scaffold.py` has 0 changes; the implementation was never committed.

**Why:** Tests can pass against stubs or unchanged code; a green CI with no implementation changes ships dead-end work that silently does nothing.
