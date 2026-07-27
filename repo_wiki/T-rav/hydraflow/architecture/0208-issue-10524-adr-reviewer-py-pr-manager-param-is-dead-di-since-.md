---
id: 0208
topic: architecture
source_issue: 10524
source_phase: plan
created_at: 2026-07-25T07:08:18.759602+00:00
status: active
corroborations: 1
---

# adr_reviewer.py pr_manager param is dead DI since commit b11e4c7a

`ADRCouncilReviewer.__init__`'s `pr_manager` param survived commit `b11e4c7a` (#5741) as dead DI: that commit migrated all six GitHub-touching call sites from `self._prs.create_issue(...)` (wired by #1823) to the module-level `_write_adr_decision(...)` JSONL sidecar consumed by `dashboard_routes/_routes.py`, but left the constructor param behind. The only real GitHub path left is `_commit_acceptance`, which opens PRs via `auto_pr.generate_and_open_pr_async` with a raw gh token, not the injected PR manager.

**Why:** before assuming a constructor param is load-bearing DI, check git history for a migration commit that silently orphaned it — #10523 papered over this with a rename/suppression instead of deleting it.
