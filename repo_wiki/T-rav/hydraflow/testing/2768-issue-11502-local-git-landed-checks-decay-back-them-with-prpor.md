---
id: 2768
topic: testing
source_issue: 11502
source_phase: plan
created_at: 2026-08-21T01:24:51.844552+00:00
status: active
corroborations: 1
---

# Local git landed-checks decay — back them with PRPort state read

The two-dot diff in `WorkspaceGCLoop` goes non-empty the moment any unrelated PR lands on the base branch, so a git-only check has a narrow validity window. The durable answer is `PRPort.get_branch_pr_state(branch)` returning `MERGED`, implemented via `gh api` in `GitHubPRManager`.

**Why:** A git-only fix passes in a fresh test repo but silently stops working in production after the next sibling PR lands on `staging` — the GitHub state read is what makes the reap durable.
