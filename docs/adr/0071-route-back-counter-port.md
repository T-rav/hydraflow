# ADR-0071 — RouteBackCounterPort: Testable Counter for Precondition Route-Backs

**Status:** Accepted
**Date:** 2026-05-19
**Enforced by:** tests/test_route_back.py

## Context

`RouteBackCoordinator` must increment a per-issue counter each time it routes an issue back to its upstream stage, and escalate to HITL once the counter exceeds `max_route_backs`. The natural home for that counter is `StateTracker`, which already owns per-issue state. However, passing the full `StateTracker` to the coordinator couples it to a large, stateful object with many concerns unrelated to route-back counting.

Additionally, the coordinator needs a rollback capability: if the counter is incremented but the subsequent label swap fails (network blip), the counter must be decremented so the issue does not burn through its route-back budget without an actual route-back having occurred.

## Decision

Define `RouteBackCounterPort` as a local `@runtime_checkable Protocol` in `src/route_back.py` with three methods:

- `get_route_back_count(issue_id)` — returns the current count
- `increment_route_back_count(issue_id)` — returns the new count after incrementing
- `decrement_route_back_count(issue_id)` — returns the new count after decrementing; must no-op and return 0 when the counter is already at 0

Production wiring passes `StateTracker`. Tests pass a small in-memory dict implementation.

## Consequences

- `RouteBackCoordinator` unit tests do not need a `StateTracker`; a five-line dict stub satisfies the port.
- The rollback invariant (decrement no-ops at zero) is enforced by `tests/test_route_back.py`, which tests the coordinator's behavior when a label swap fails mid-route-back.
- The full state-tracker integration (persisting the counter across restarts) lives on `StateTracker` and is covered by state-layer tests.

## Alternatives considered

- **Pass StateTracker directly.** Simpler wiring but couples the coordinator to the full state layer; harder to test.
- **Use an integer attribute on the coordinator.** In-memory only; counter resets on orchestrator restart, causing route-back loops to be invisible across restarts.

## Related

- `src/route_back.py:RouteBackCounterPort`, `src/route_back.py:RouteBackCoordinator`
- `src/state.py:StateTracker` — production implementation
- `tests/test_route_back.py` — enforces the rollback invariant
