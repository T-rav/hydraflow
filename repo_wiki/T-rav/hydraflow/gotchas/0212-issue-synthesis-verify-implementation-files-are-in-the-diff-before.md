---
id: 0212
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:47:09.161704+00:00
status: active
corroborations: 1
supersedes: 0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179
---

# Verify implementation files are in the diff before merging

Before merging, confirm the target source file appears in `git diff --name-only origin/main`.

Example: PR closes #7644 but `git diff --name-only` shows only `docs/` and `tests/` — `src/makefile_scaffold.py` has 0 changes.

**Why:** Tests can pass against stubs or unchanged code; a green CI with no implementation changes ships dead-end work that silently does nothing.
