---
id: 1407
topic: gotchas
source_issue: 11275
source_phase: plan
created_at: 2026-08-15T20:45:30.666447+00:00
status: active
corroborations: 1
---

# pr_manager._issue_number_from_branch scoped to agent/issue- only

Keep `_issue_number_from_branch` in `src/pr_manager.py` scoped to `agent/issue-` only. Auto-agent PRs are shepherded by `DependabotMergeLoop`, which matches the full prefix on `pr.branch` directly.

Callers (`list_open_prs`, `list_prs_by_label`, HITL intake) feed the review→merge pipeline keyed on `hydraflow-review` + `agent/issue-N`. A future "consolidate parsers" pass that widens this function risks routing auto-agent preflight PRs into the review→merge pipeline.

**Why:** The scoping is deliberate separation of concerns between the review→merge and Dependabot merge loops.
