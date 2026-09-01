---
id: 0441
topic: architecture
source_issue: 11947
source_phase: plan
created_at: 2026-09-01T10:45:05.630230+00:00
status: active
corroborations: 1
---

# AST-scan importers; regex misses parenthesized imports

Use `ast.ImportFrom` to scan importers, not a single-line regex. The 2026-08-18 `mode_mismatch` incident's import was a parenthesized multi-line `from mode_mismatch import (\n name1,\n name2,\n)` — a regex `from X import Y` pattern missed it entirely, producing a false negative on a real symbol drop.

- `scripts/check_symbol_drop.py` prefilters with `git grep -lE`, then AST-confirms via `ast.ImportFrom`.
- Test case in `tests/test_check_symbol_drop.py` covers parenthesized multi-line import.

**Why:** Regex import matching silently misses real-world multi-line imports, making a gate that looks correct but passes green on the exact incident it was built to catch.
