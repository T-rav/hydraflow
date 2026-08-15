---
id: 1349
topic: gotchas
source_issue: 11182
source_phase: plan
created_at: 2026-08-14T23:30:09.293949+00:00
status: active
corroborations: 1
---

# Promote branch-name literals to a single config source of truth

When a branch-name literal (e.g. `agent/auto-agent-`) is written independently in multiple modules, minting and parsing drift apart silently. Promote one public constant + helper in `src/config.py` and derive every site from it.

- `HydraFlowConfig.auto_agent_branch_for_issue()` mirrors `branch_for_issue`
- Minting (`auto_agent_preflight_loop._resolve_worktree`), prefix match (`dependabot_merge_loop`), and GC parsing (`workspace_gc_loop._ISSUE_BRANCH_RES`) all reference the constant
- Delete private `_AUTO_AGENT_BRANCH_PREFIX` aliases rather than keeping them

**Why:** Independent copies of the same literal across modules mean a parser can fail to recognize a branch the minter actually creates, leaking orphaned branches through GC.
