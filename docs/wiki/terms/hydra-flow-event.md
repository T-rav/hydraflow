---
id: "01KTAN3MGDRZ1MGQ21Z2Q2XM8Z"
name: "HydraFlowEvent"
kind: "domain_event"
bounded_context: "shared-kernel"
code_anchor: "src/events.py:HydraFlowEvent"
aliases: ["event", "bus event", "orchestrator event"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-06-05T01:07:07.917376+00:00"
updated_at: "2026-06-05T01:07:07.917379+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-06-05T01:07:07.917287+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 4
---

## Definition

A single typed message published on the EventBus, carrying a monotonic id, an EventType discriminator, a UTC timestamp, a freeform payload map, and optional session and repository scope. Every in-process state change — phase transitions, worker updates, CI checks, HITL escalations, epic lifecycle milestones — is communicated across the system as a HydraFlowEvent, making it the universal unit of observable state in the orchestrator. Callers construct and publish instances directly; subscribers receive them via async queues and may cast the payload to a typed dict via typed_data().

## Invariants

- id is monotonically increasing and always exceeds any previously persisted historical event id (enforced by _Counter.advance after log replay)
- Ephemeral event types (e.g. PIPELINE_SNAPSHOT) are fanned out live but never retained in in-memory history nor written to the on-disk EventLog
- timestamp is always a UTC ISO-8601 string produced at construction time
