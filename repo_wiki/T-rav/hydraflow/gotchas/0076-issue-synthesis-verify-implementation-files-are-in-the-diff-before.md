---
id: 0076
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:16:33.342420+00:00
status: superseded
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
superseded_by: 0078
---

# Verify implementation files are in the diff before merging feature PR

Before merging, confirm the target source file appears in `git diff --name-only origin/main`.

Example: PR closes #7644 but `git diff --name-only` shows only `docs/` and `tests/` — `src/makefile_scaffold.py` has 0 changes; the implementation was never committed.

**Why:** Tests can pass against stubs or unchanged code; a green CI with no implementation changes ships dead-end work that silently does nothing.
