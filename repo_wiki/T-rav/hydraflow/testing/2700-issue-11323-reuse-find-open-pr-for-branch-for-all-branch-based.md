---
id: 2700
topic: testing
source_issue: 11323
source_phase: plan
created_at: 2026-08-16T09:14:32.110027+00:00
status: active
corroborations: 1
---

# Reuse find_open_pr_for_branch for all branch-based PR queries

Use `PRManager.find_open_pr_for_branch` (`src/pr_manager.py:499`) as the single entry point for `gh api .../pulls?state=open&head=<owner>:<branch>` queries.
- It already handles contracts-boundary parsing; adding a third inline query shape duplicates that logic and risk.
- The private helper for multi-branch fallback should call it per-candidate rather than issuing its own `gh api`.

**Why:** Proliferating ad-hoc `gh api` query shapes in `pr_manager.py` creates inconsistent error handling and test coverage gaps.
