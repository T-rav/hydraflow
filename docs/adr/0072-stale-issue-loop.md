# ADR-0072 — StaleIssueLoop: Auto-Close Stale General Issues

**Status:** Proposed
**Date:** 2026-05-19
**Enforced by:** tests/test_stale_issue_loop.py

## Context

The repository accumulates open issues that have no HydraFlow lifecycle label
(`planner`, `ready`, `review`, `hitl`) and have seen no activity for an
extended period. These are "general" issues — feature requests, questions, or
bug reports that did not enter the pipeline or were abandoned before triage.
Left open indefinitely, they create noise in the GitHub issue list and in the
pipeline's view of available work.

A separate concern — stale HITL escalation issues — is handled by
`StaleIssueGCLoop`, which targets issues carrying the HITL label, posts a
farewell comment, and caps at 10 closes per cycle. The two loops have
effectively zero business-logic overlap; they share only the
`BaseBackgroundLoop` framework.

## Decision

Introduce `StaleIssueLoop`, a `BaseBackgroundLoop` that periodically scans for
open issues without a HydraFlow lifecycle label. For each issue whose
`updated_at` timestamp is older than the per-tag threshold configured in
`StateTracker.get_stale_issue_settings()`, the loop closes the issue via
`PRManager`. A set of previously-closed issue IDs is maintained in
`StateTracker.get_stale_issue_closed()` to prevent re-closing issues that were
deliberately reopened.

Kill-switch: `enabled_cb("stale_issue")` AND `config.stale_issue_loop_enabled`.

## Consequences

- Old, abandoned general issues drain from the open-issue list without
  operator intervention.
- The per-tag threshold allows operators to configure different inactivity
  windows for different issue types (e.g. shorter window for `question`
  labels, longer for `bug`).
- `ObservabilityPort` is optional in the constructor (`observability: ObservabilityPort | None = None`); callers that do not have Sentry wired can pass `None`.

## Alternatives considered

- **Use `StaleIssueGCLoop` for all stale issues.** Rejected: HITL escalations require a farewell comment and stricter caps; combining the two created a scope-creep risk and made per-class thresholds harder to configure.
- **Manual triage only.** Does not scale; stale issues accumulate faster than manual review cycles.

## Related

- `src/stale_issue_loop.py:StaleIssueLoop`
- `src/stale_issue_gc_loop.py:StaleIssueGCLoop` — complement for HITL escalations
- [ADR-0029](0029-caretaker-loop-pattern.md) — Caretaker Background Loop Pattern
- `docs/wiki/gotchas.md` — "StaleIssueLoop vs StaleIssueGCLoop — distinct scopes, zero business-logic overlap"
