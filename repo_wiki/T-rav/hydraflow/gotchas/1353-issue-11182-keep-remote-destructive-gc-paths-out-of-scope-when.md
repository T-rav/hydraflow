---
id: 1353
topic: gotchas
source_issue: 11182
source_phase: plan
created_at: 2026-08-14T23:30:09.294033+00:00
status: stale
corroborations: 1
stale_reason: source issue #11182 closed
---

# Keep remote-destructive GC paths out of scope when widening local attribution

When widening `WorkspaceGCLoop` branch attribution, deliberately leave `branch_gc_scan._AGENT_BRANCH_RE` and `stale_issue_loop._BRANCH_GC_PREFIXES` unchanged — those drive destructive *remote* branch deletes and PR state.

- Local `git branch -D` in phase 3 is recoverable; remote deletes via `StaleIssueLoop` are not
- Phase 3 checks pipeline/HITL labels but not `_has_open_pr`, so widening eligibility reaches unpushed work on attempt-exhausted branches
- File remote-widening as a separate follow-up issue

**Why:** Bundling local and remote destructive-behaviour changes in one PR increases blast radius without independent review of each surface.
