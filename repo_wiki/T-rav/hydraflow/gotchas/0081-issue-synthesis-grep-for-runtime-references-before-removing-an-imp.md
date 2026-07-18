---
id: 0081
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T19:10:32.482255+00:00
status: active
corroborations: 1
supersedes: 0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077
---

# Grep for runtime references before removing an import

Before deleting an import, grep the file for runtime uses: `isinstance()` calls, variable assignments, and decorator calls.

Example: `grep -n 'MyClass' src/foo.py` — a hit in `isinstance(x, MyClass)` means the import is load-bearing even if type checkers flag it as unused.

**Why:** Ruff's `F401` rule does not inspect `isinstance` call sites; removing an apparently-unused import that is used at runtime produces `NameError`.
