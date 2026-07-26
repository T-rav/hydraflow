---
id: 0244
topic: architecture
source_issue: 10644
source_phase: plan
created_at: 2026-07-26T12:01:31.012830+00:00
status: active
corroborations: 1
---

# Shared root cause: fix render once, pin both issues

When two escape-ledger issues (#10644 and #10646) share a root cause in `_render_finding`, fix the render path once and keep both regression test files (`tests/regressions/test_issue_10644.py` and `tests/regressions/test_issue_10646.py`).

- Do not delete the sibling test — it pins a different record shape for a separate open issue.
- Do not implement a second fix in `_surfacing_answered` or the CLI — that breaks the aging close path already pinned by the scenario suite.

**Why:** Deleting sibling coverage strands the other issue; duplicating the fix across service/CLI/render layers violates the narrowest-fix-boundary principle and risks regressions on already-green paths.
