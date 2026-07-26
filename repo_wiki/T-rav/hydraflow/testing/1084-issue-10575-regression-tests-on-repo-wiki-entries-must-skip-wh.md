---
id: 1084
topic: testing
source_issue: 10575
source_phase: plan
created_at: 2026-07-26T00:41:55.611457+00:00
status: active
corroborations: 1
---

# Regression tests on repo_wiki entries must skip when files are pruned

repo_wiki entries expire via a 90-day stale prune driven by `RepoWikiLoop`'s `active_lint_tracked` lifecycle, so a closed issue's entries (e.g. 0204/0842/0843) flip to `status: stale` on the next tick — don't assert `status: active` in corrective PRs. Any `tests/regressions/*.py` asserting content of specific entry files must skip cleanly when those files are absent, not fail. **Why:** an unconditional file-existence assertion turns a routine lifecycle prune into a false CI failure.
