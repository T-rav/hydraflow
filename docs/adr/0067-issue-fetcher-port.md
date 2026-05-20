# ADR-0067 — IssueFetcherPort: GitHub Issue Fetching Boundary

**Status:** Proposed
**Date:** 2026-05-19
**Enforced by:** (none) — structural subtype check planned for `tests/test_ports.py` in follow-up

## Context

Domain code (phases, background loops) needs to fetch GitHub issues. The concrete `IssueFetcher` class carries significant infrastructure: `gh` CLI subprocess calls, rate-limit back-off with jitter, two internal caches (PR cache, collaborator cache), and `IncompleteIssueFetchError` retry logic. Domain code does not need any of that; it needs two operations — single-issue lookup and label-scoped batch fetch.

Without a formal port, phases imported `IssueFetcher` directly, making them depend on the full infrastructure stack and harder to test (every test that touches a phase had to mock the entire `IssueFetcher` surface).

## Decision

Define `IssueFetcherPort` as a `@runtime_checkable Protocol` in `src/ports.py` with exactly two methods:

- `fetch_issue_by_number(issue_number)` — returns `GitHubIssue | None`
- `fetch_issues_by_labels(labels, limit, exclude_labels, require_complete)` — returns `list[GitHubIssue]`

`IssueFetcher` satisfies this port via structural subtyping. Tests pass `AsyncMock(spec=IssueFetcherPort)`. The concrete class retains all infrastructure methods (PR cache, collaborator cache, etc.) that stay off the port.

## Consequences

- Phases and loops depend only on the two-method surface they actually use.
- Tests no longer need to mock the full `IssueFetcher` surface.
- Infrastructure methods on the concrete class can evolve without touching the port.

## Alternatives considered

- **Pass `IssueFetcher` directly.** Simpler but couples domain code to the infrastructure layer and makes tests heavier.
- **One method per call site.** More granular ports make injection boilerplate grow; two methods cover all domain call sites.

## Related

- `src/ports.py:IssueFetcherPort` — the port definition
- `src/issue_fetcher.py:IssueFetcher` — the concrete adapter
- [ADR-0044](0044-hydraflow-principles.md) — four-layer architecture
