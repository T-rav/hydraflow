---
id: 3473
topic: patterns
source_issue: 11323
source_phase: plan
created_at: 2026-08-16T09:14:32.110017+00:00
status: superseded
corroborations: 1
superseded_by: 3619
---

# PRManager must check canonical then Auto-Agent branch for PRs

PR lookups for an issue must walk both branch conventions in order: `config.branch_for_issue(n)` first, then `config.auto_agent_branch_for_issue(n)`.
- A fix pushed by an Auto-Agent session to `agent/auto-agent-<N>` (#11182) reads as "no PR" if only the canonical `agent/issue-<N>` is checked.
- Use a private helper that returns the first branch with an open PR; canonical wins on conflict.

**Why:** Single-branch checks silently miss Auto-Agent PRs, breaking both HITL display and epic merge coordination.
