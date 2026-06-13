---
id: "01KT3WKPR5MN8QJ14CF77W6K1"
name: "IssueFetcherPort"
kind: "port"
bounded_context: "shared-kernel"
code_anchor: "src/ports.py:IssueFetcherPort"
aliases: ["issue fetcher port", "github issue fetching port"]
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K9"}, {"kind": "depends_on", "target": "01KR1GDECRP5Z9X3HNGX3XFS8B"}]
evidence: ["01KQNYZRM4B7DX9MWDQFHF488F", "01KRBX2N4QP7VW8FGH3J5YD0M2", "01KRBX2N4QP7VW8FGH3J5YD0M6"]
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T00:00:00.000000+00:00"
updated_at: "2026-06-12T04:18:46.416686+00:00"
---

## Definition

Hexagonal port for fetching GitHub issues from the upstream source of truth. Exposes two methods consumed by domain code (phases and background loops): `fetch_issue_by_number` for single-issue lookups and `fetch_issues_by_labels` for label-scoped batch fetches. Implemented by `issue_fetcher.IssueFetcher`, which shells out to the `gh` CLI and applies internal caching and rate-limit back-off.

## Invariants

- Pure Protocol — no implementation, no state.
- Only the two methods domain code actually calls are declared here; the concrete `IssueFetcher` carries additional infrastructure methods (PR cache, collaborator cache) that stay off the port.
- `fetch_issues_by_labels` accepts an optional `exclude_labels` list and a `require_complete` flag so callers can narrow results without extra filtering passes.
