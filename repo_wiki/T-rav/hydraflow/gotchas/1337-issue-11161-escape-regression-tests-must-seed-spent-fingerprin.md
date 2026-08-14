---
id: 1337
topic: gotchas
source_issue: 11161
source_phase: review
created_at: 2026-08-14T20:59:54.755898+00:00
status: active
corroborations: 1
---

# Escape regression tests must seed spent-fingerprint production state

Regression tests for escape resolution must seed the actual production condition — an already-surfaced/spent fingerprint — and drive the full `_surface_findings` pipeline through a real git repo. Do not pin `_auto_diagnose` inputs or bypass `EscapeAutoDiagnoser`/`regression_hits` git-grep.

- `tests/regressions/test_issue_11161.py` pinned diagnosis inputs and skipped the already-surfaced state, so it could not catch the real ordering bug.
- Add a real-git-repo test that pre-seeds an `already_surfaced` fingerprint matching the live escape, then runs `_surface_findings` end-to-end.

**Why:** Pinning bypasses the exact code path (fingerprint exclusion → diagnosis) that fails in production.
