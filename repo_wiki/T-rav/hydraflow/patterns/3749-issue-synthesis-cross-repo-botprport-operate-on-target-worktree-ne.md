---
id: 3749
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T13:50:50.550558+00:00
status: superseded
corroborations: 1
supersedes: 3604
superseded_by: 3894
---

# Cross-repo BotPRPort: operate on target worktree, never HydraFlow tree

When implementing a second `BotPRPort` (e.g. `CrossRepoBotPRPort`), point `auto_pr.generate_and_open_pr_async` at the target's local checkout (`RepoRecord.path`) so worktree/commit/push/`gh pr create` act entirely on the target. Only a worktree branch is pushed — direct pushes to origin are structurally impossible. Verify HydraFlow's checkout is clean: `git status --porcelain` must be empty after the flow.

**Why:** Without worktree isolation, cross-repo remediation risks mutating HydraFlow's own working tree and pushing to the wrong remote.
