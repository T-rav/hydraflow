---
id: 1361
topic: gotchas
source_issue: 11188
source_phase: plan
created_at: 2026-08-15T00:25:53.081755+00:00
status: active
corroborations: 1
---

# Branch name beats commit message for issue-number resolution

Auto-agent branches (`agent/auto-agent-<N>`) carry no `Fixes #N` commit, so the branch name is the only route off `issue_number == 0`. The name regex must also reject bad suffixes (`agent/auto-agent-abc`, `agent/auto-agent-` → 0).

- `src/branch_gc_scan.py` → `extract_issue_number`, `_AUTO_AGENT_BRANCH_RE`
- Branch name takes precedence over a conflicting `Fixes #1` in commits.

**Why:** Relying on commit keywords alone would leave auto-agent branches permanently unresolved and un-GC-able.
