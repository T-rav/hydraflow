---
id: 0217
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:45:05.793266+00:00
status: active
corroborations: 1
supersedes: 0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213
---

# Grep for runtime references before removing an import

Before deleting an import, grep the file for runtime uses: `isinstance()` calls, variable assignments, and decorator calls.

Example: `grep -n 'MyClass' src/foo.py` — a hit in `isinstance(x, MyClass)` means the import is load-bearing even if type checkers flag it as unused.

**Why:** Ruff's `F401` rule does not inspect `isinstance` call sites; removing an apparently-unused import that is used at runtime produces `NameError`.

See also: gotchas — Ruff strips unused imports mid-TDD cycle.
