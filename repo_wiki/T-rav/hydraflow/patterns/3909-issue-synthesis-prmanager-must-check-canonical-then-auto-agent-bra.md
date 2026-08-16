---
id: 3909
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T15:30:58.382520+00:00
status: superseded
corroborations: 1
supersedes: 3764
superseded_by: 4056
---

# PRManager must check canonical then Auto-Agent branch for PRs

PR lookups for an issue must walk both branch conventions in order: `config.branch_for_issue(n)` first, then `config.auto_agent_branch_for_issue(n)`.

Example: A fix pushed by an Auto-Agent session to `agent/auto-agent-<N>` (#11182) reads as "no PR" if only the canonical `agent/issue-<N>` is checked. Use a private helper that returns the first branch with an open PR; canonical wins on conflict.

**Why:** Single-branch checks silently miss Auto-Agent PRs, breaking both HITL display and epic merge coordination.
