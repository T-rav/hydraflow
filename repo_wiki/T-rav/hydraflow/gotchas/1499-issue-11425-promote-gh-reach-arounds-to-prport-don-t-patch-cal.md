---
id: 1499
topic: gotchas
source_issue: 11425
source_phase: plan
created_at: 2026-08-18T04:29:33.971173+00:00
status: active
corroborations: 1
---

# Promote gh reach-arounds to PRPort, don't patch call sites

Promote non-adapter `gh` calls to `PRPort` methods before widening the fake conformance guard — order is load-bearing.
- `#11418` branch-GC reads (`list_branch_refs`, `list_branch_commits`) move off `_prs._run_gh` / `_prs._repo` in `src/stale_issue_loop.py` into `src/ports.py` / `src/pr_manager.py`.
- A call that never crosses `PRPort` can't be modelled by `FakeGitHub`, so promoting deletes the drift category rather than chasing individual sites.
**Why:** Patching call sites leaves the reach-around category alive for the next caller; only Port promotion lets the conformance guard enforce.
