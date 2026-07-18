---
id: 0047
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:16:33.332292+00:00
status: active
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
---

# Grep for runtime references before removing an import

Before deleting an import, grep the file for runtime uses: `isinstance()` calls, variable assignments, and decorator calls.

Example: `grep -n 'MyClass' src/foo.py` — a hit in `isinstance(x, MyClass)` means the import is load-bearing even if type checkers flag it as unused.

**Why:** Ruff's `F401` rule does not inspect `isinstance` call sites; removing an apparently-unused import that is used at runtime produces `NameError`.
