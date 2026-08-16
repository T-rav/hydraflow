---
id: 2677
topic: testing
source_issue: 11222
source_phase: plan
created_at: 2026-08-16T05:46:03.675017+00:00
status: active
corroborations: 1
---

# Locate CI steps by run: substring, never by index or name

In `tests/test_console_conformance.py` and `tests/regressions/test_issue_*.py`, find workflow steps by matching a substring of their `run:` field (e.g. `'make audit'`, `'make console-conformance'`). Never use list indices or `name:` fields — steps get reordered and renamed. When asserting on env vars, merge job-level `env:` under step-level `env:`, resolve `${{ github.* }}` against a supplied base, and skip unresolvable expressions like `secrets.*`. **Why:** index/name-based locators silently bind to the wrong step after workflow edits, producing false greens.
