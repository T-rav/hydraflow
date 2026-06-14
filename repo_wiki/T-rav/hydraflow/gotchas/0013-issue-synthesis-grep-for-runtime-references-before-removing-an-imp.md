---
id: 0013
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.693090+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# Grep for runtime references before removing an import

Before deleting an import, grep the file for runtime uses: `isinstance()` calls, variable assignments, and decorator calls.

Example: `grep -n 'MyClass' src/foo.py` — a hit in `isinstance(x, MyClass)` means the import is load-bearing even if type checkers flag it as unused.

**Why:** Ruff's `F401` rule does not inspect `isinstance` call sites; removing an apparently-unused import that is used at runtime produces `NameError`.
