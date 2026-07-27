---
id: "01KYABBX5P03FV3ZFMPWFRFY48"
name: "GitHubDataCache"
kind: "service"
bounded_context: "shared-kernel"
code_anchor: "src/github_cache_loop.py:GitHubDataCache"
aliases: ["github data cache", "shared github snapshot", "gh api cache"]
related: [{"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9C1"}, {"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9B2"}, {"kind": "depends_on", "target": "01KR9A3F20M01PGF32CF88W9A4"}, {"kind": "depends_on", "target": "01KYABD5XVX4ZXFXT3Z76KMQZ0"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K2"}, {"kind": "depends_on", "target": "01KWDRENTS7VACCW9PDA7Y488H"}, {"kind": "depends_on", "target": "01KY4QGA4VF2GJDCW3ZVKNBPMY"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K5"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-24T15:19:40.470565+00:00"
updated_at: "2026-07-26T10:16:32.370693+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-07-24T15:19:40.470503+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 3
---

## Definition

GitHubDataCache is a repo-scoped, in-memory and disk-persisted cache for GitHub API read data. A single GitHubCacheLoop poller fetches data on a fixed interval and stores it here; dashboard endpoints and background workers such as DependabotMergeLoop, FlakeTrackerLoop, and RCBudgetLoop read from it via get_* methods instead of each issuing their own gh api calls. High-frequency datasets (open PRs, HITL items, label counts, collaborators) are refreshed by the poll cycle, while low-frequency datasets (RC-promotion workflow runs, xdist-audit runs, per-label issue lists) are demand-refreshed with an explicit staleness bound, single-flight locking to coalesce concurrent refreshes, and a stale-serve fallback before returning empty.

## Invariants

- get_* read methods never hit the network — only poll() and the demand-refresh paths call the GitHub API
- Demand-refreshed datasets serve a stale snapshot while younger than a multiple (default 3x) of the caller's staleness bound; beyond that, callers get an empty result rather than acting on ancient data
- The cache is repo-scoped: each RepoRuntime gets its own instance with its own disk file
