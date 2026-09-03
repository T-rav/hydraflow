---
id: 1577
topic: gotchas
source_issue: 12062
source_phase: plan
created_at: 2026-09-02T22:21:22.693565+00:00
status: active
corroborations: 1
---

# Worktree pre-commit hook rejects bot PRs touching arch inputs

Term files (`docs/wiki/terms/`), wiki entries (`docs/wiki/`), and standards that touch arch inputs fail pre-commit unless `docs/arch/generated/` artifacts regenerate. Bot PR callers stage only their own files; `src/auto_pr.py` never auto-regenerates, triggering staleness check. Regression test: `tests/regressions/test_issue_12062.py`.
