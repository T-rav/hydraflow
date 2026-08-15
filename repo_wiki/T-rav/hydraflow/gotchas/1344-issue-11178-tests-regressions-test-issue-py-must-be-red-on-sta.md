---
id: 1344
topic: gotchas
source_issue: 11178
source_phase: plan
created_at: 2026-08-14T23:03:00.703679+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# tests/regressions/test_issue_*.py must be RED on staging before src change

Regression pin tests under `tests/regressions/` must fail on the current staging branch before the `src/` fix lands. Write the test first, confirm RED, then implement.

- If a pre-existing untracked file exists from an earlier investigation, rewrite it — its premise may be stale (e.g., diagnosis below `_resolve_range` early exits).

**Why:** A green-before-fix regression test is vacuous; it proves nothing about the fix it guards.
