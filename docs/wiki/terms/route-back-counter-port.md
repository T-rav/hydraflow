---
id: "01KT3WKPR5MN8QJ14CF77W6K4"
name: "RouteBackCounterPort"
kind: "port"
bounded_context: "shared-kernel"
code_anchor: "src/route_back.py:RouteBackCounterPort"
aliases: ["route-back counter port", "route back counter", "precondition retry counter port"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T00:00:00.000000+00:00"
updated_at: "2026-05-19T00:00:00.000000+00:00"
---

## Definition

Hexagonal port for the per-issue route-back counter. Lives in `src/route_back.py` alongside `RouteBackCoordinator`. The coordinator depends on this port rather than `StateTracker` directly, so unit tests can wire a tiny in-memory dict implementation without pulling in the full state layer. Production wiring connects `StateTracker` as the concrete adapter.

## Invariants

- Pure Protocol — no implementation, no state.
- Three methods: `get_route_back_count` reads the current count; `increment_route_back_count` returns the new count after incrementing; `decrement_route_back_count` rolls back an increment when a subsequent label swap fails, preventing transient network blips from burning route-back budget without any actual route-back occurring.
- `decrement_route_back_count` must be a no-op (returning 0) when the counter is already at zero.
