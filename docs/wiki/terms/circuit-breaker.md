---
id: "01KZZTMMG25DET54FHSH9WK37S"
name: "CircuitBreaker"
kind: "control_role"
bounded_context: "shared-kernel"
code_anchor: "src/circuit_breaker.py:CircuitBreaker"
aliases: ["circuit breaker", "breaker"]
related: [{"kind": "depends_on", "target": "01KZ0F1YAK45A6FBKM7MAJ7H5D"}, {"kind": "depends_on", "target": "01KY9SS1BTZMWRAW2VRS3WPBCG"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-08-14T09:46:20.035148+00:00"
updated_at: "2026-08-14T09:46:20.035177+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-08-14T09:46:20.034076+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 2
---

## Definition

Three-state (CLOSED → OPEN → HALF_OPEN → CLOSED) resilience primitive that protects against cascading failures by opening after `max_failures` consecutive failures and probing HALF_OPEN after `reset_timeout` seconds. Re-exported from `signal_control.controllers` alongside `PidController`, `AimdController`, and `RetryController` as a peer in the control vocabulary, and used by subprocess execution to gate calls that may raise `CreditExhaustedError`.

## Invariants

- After `max_failures` consecutive failures, state transitions to OPEN and `allow_request()` returns False.
- State transitions OPEN → HALF_OPEN only after `reset_timeout` seconds have elapsed since the last failure.
- A success recorded in HALF_OPEN or CLOSED zeroes the failure count and returns state to CLOSED.
