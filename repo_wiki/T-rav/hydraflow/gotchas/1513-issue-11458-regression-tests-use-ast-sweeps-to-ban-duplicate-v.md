---
id: 1513
topic: gotchas
source_issue: 11458
source_phase: plan
created_at: 2026-08-18T12:25:44.377211+00:00
status: active
corroborations: 1
---

# Regression tests use AST sweeps to ban duplicate vocabulary literals

Acceptance pins in `tests/regressions/test_issue_*.py` can include AST sweeps over all of `src/` that fail if any file outside the owner module spells both `COMPLETED` and `NOT_PLANNED` in a set/tuple/list literal. When collapsing hand-maintained vocabulary copies, only the defining module (e.g., `src/issue_state.py`) is exempt.

**Why:** Without an AST sweep, drift between copies is undetectable — a developer adds a new state to one site and silently misses the other three.
