---
id: 1691
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T02:43:14.334530+00:00
status: superseded
corroborations: 1
supersedes: 1608
superseded_by: 1785
---

# Regression tests on repo_wiki entries must skip when pruned

repo_wiki entries expire via a 90-day stale prune driven by RepoWikiLoop's active_lint_tracked lifecycle — any tests/regressions/*.py asserting content of specific entry files must skip cleanly when absent, not fail.

Example: don't assert `status: active` in corrective PRs; closed-issue entries (e.g. 0204/0842/0843) flip to `status: stale` on the next tick.

**Why:** An unconditional file-existence assertion turns a routine lifecycle prune into a false CI failure.
