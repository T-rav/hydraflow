---
id: 0178
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:23:52.957252+00:00
status: active
corroborations: 1
supersedes: 0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145
---

# Verify implementation files are in the diff before merging

Before merging, confirm the target source file appears in `git diff --name-only origin/main`.

Example: PR closes #7644 but `git diff --name-only` shows only `docs/` and `tests/` — `src/makefile_scaffold.py` has 0 changes.

**Why:** Tests can pass against stubs or unchanged code; a green CI with no implementation changes ships dead-end work that silently does nothing.
