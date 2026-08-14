---
id: 1315
topic: gotchas
source_issue: 11138
source_phase: plan
created_at: 2026-08-14T14:08:04.915453+00:00
status: active
corroborations: 1
---

# Commit RED pin regression tests unchanged alongside the fix

`tests/regressions/test_issue_11138.py` is created as a RED pin — a failing test that documents the bug before the fix. Verify it fails with the exact bug output (`'HEAD:tests/…' != 'tests/…'`), then commit unchanged alongside the fix.

- Pattern: write the regression test first, run it, confirm RED, implement the fix, re-run to GREEN.
- The pin covers both the `_grep` adapter and the end-to-end ledger note.

**Why:** Committing the RED pin alongside the fix proves the test would have caught the original regression and guards against reintroduction of the `HEAD:` prefix drift.
