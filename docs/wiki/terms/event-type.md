---
id: "01KXTTERTWZZEW65AZZQ8R1AZF"
name: "EventType"
kind: "value_object"
bounded_context: "shared-kernel"
code_anchor: "src/events.py:EventType"
aliases: ["event category", "event kind"]
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6KA"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K5"}, {"kind": "depends_on", "target": "01KWDRENTS7VACCW9PDA7Y488H"}, {"kind": "depends_on", "target": "01KWDRENTS7VACCW9PDA7Y488G"}, {"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9C1"}, {"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9B9"}, {"kind": "depends_on", "target": "01JZ9FK3C0M02HYR42BF22W0B2"}, {"kind": "depends_on", "target": "01KWDRENTS7VACCW9PDA7Y488F"}, {"kind": "depends_on", "target": "01KWDRENTS7VACCW9PDA7Y488D"}, {"kind": "depends_on", "target": "01KR9A3F20M01PGF32CF88W9A5"}, {"kind": "depends_on", "target": "01KR9A3F20M01PGF32CF88W9A9"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-18T14:35:32.060351+00:00"
updated_at: "2026-07-18T14:35:32.060353+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-07-18T14:35:32.060298+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 9
---

## Definition

Closed enumeration of event categories published by the orchestrator on the EventBus. Each member — from PHASE_CHANGE and WORKER_UPDATE to PR_CREATED and HITL_ESCALATION — names a distinct class of system happening that subscribers filter on. A frozenset subset (EPHEMERAL_EVENT_TYPES, currently just PIPELINE_SNAPSHOT) is delivered live-only and excluded from in-memory history and on-disk persistence to prevent stale-snapshot clobber on WebSocket reconnect.

## Invariants

- Every HydraFlowEvent carries exactly one EventType as its type discriminator.
- EPHEMERAL_EVENT_TYPES members are fanned out to live subscribers but never retained in history nor persisted to the on-disk event log.
