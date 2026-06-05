---
id: "01KR9A3F20M01PGF32CF88W9A2"
name: "GitHubCacheLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/github_cache_loop.py:GitHubCacheLoop"
aliases: ["github cache loop", "github data cache loop", "github poller"]
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K5"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K2"}, {"kind": "implements", "target": "01KQV37D10M06PGF32CF77W6K5"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T20:00:00.000000+00:00"
updated_at: "2026-06-05T01:03:42.463501+00:00"
---

## Definition

Centralized GitHub data poller that replaces the pattern where every dashboard endpoint and background worker makes its own `gh api` calls (ADR-0041). A single `GitHubCacheLoop` polls GitHub on a fixed interval and stores results in `GitHubDataCache` — in memory and on disk. Dashboard endpoints and background workers read from the cache instantly rather than hitting the API. Write operations (create PR, merge, comment, label swap) still call `gh` directly because they need immediate confirmation.

## Invariants

- Only one instance per repo runtime; all read consumers share the same cache snapshot.
- Write operations bypass the cache and call `gh` directly.
- Cache staleness is observable: each `CacheSnapshot` carries a `fetched_at` timestamp; `age_seconds` is infinite until the first poll completes.
