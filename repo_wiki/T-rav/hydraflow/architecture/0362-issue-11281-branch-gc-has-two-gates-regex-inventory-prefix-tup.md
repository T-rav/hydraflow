---
id: 0362
topic: architecture
source_issue: 11281
source_phase: plan
created_at: 2026-08-16T01:24:32.227542+00:00
status: active
corroborations: 1
---

# Branch GC has two gates: regex + inventory prefix tuple

When adding a branch namespace to StaleIssueLoop's remote branch-GC reconciler, update BOTH gates: the attribution regex (`branch_gc_scan._AGENT_BRANCH_RE`) AND the inventory prefix tuple (`stale_issue_loop._BRANCH_GC_PREFIXES`).

Example: `agent/auto-agent-` needs `rf"^{re.escape(AUTO_AGENT_BRANCH_PREFIX)}(\d+)$"` added to `_AGENT_BRANCH_RE` **and** `AUTO_AGENT_BRANCH_PREFIX` added to `_BRANCH_GC_PREFIXES`.

Add a module-level assertion that the prefix constant ∈ the tuple to prevent regression.

**Why:** The inventory tuple drives `gh api matching-refs` calls — the regex never sees a branch that was never listed. Fixing only the regex (the issue's literal ask) ships green and fixes nothing. Precedent: `WorkspaceGCLoop._ISSUE_BRANCH_RES` from #11272.
