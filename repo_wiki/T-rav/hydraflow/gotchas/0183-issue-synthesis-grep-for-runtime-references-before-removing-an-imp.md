---
id: 0183
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:47:09.151540+00:00
status: active
corroborations: 1
supersedes: 0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179
---

# Grep for runtime references before removing an import

Before deleting an import, grep the file for runtime uses: `isinstance()` calls, variable assignments, and decorator calls.

Example: `grep -n 'MyClass' src/foo.py` — a hit in `isinstance(x, MyClass)` means the import is load-bearing even if type checkers flag it as unused.

**Why:** Ruff's `F401` rule does not inspect `isinstance` call sites; removing an apparently-unused import that is used at runtime produces `NameError`.
