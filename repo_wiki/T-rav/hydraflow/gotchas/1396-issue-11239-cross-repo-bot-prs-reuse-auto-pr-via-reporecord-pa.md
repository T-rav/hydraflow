---
id: 1396
topic: gotchas
source_issue: 11239
source_phase: plan
created_at: 2026-08-15T09:47:55.217023+00:00
status: active
corroborations: 1
---

# Cross-repo bot PRs reuse auto_pr via RepoRecord.path, fail closed early

For cross-repo bot PRs, point `generate_and_open_pr_async` at `RepoRecord.path` and resolve the target repo's base branch and `origin` remote before calling the Port; fail closed with an actionable message if either is missing. `src/rails_fix_pr_port.py` (`CrossRepoBotPRPort`, BotPRPort shape per ADR-0068) wraps `auto_pr`; `src/rails_fix.py` resolves slug→`RepoRecord.path`. **Why:** A read-only clone or non-standard base branch fails deep inside the worktree flow with an opaque error.
