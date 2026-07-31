---
id: "01KYW34KGZNXKF5N1TNB7VB731"
name: "HydraFlowEvent"
kind: "domain_event"
bounded_context: "shared-kernel"
code_anchor: "src/events.py:HydraFlowEvent"
aliases: ["bus event", "published event"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-31T12:42:12.383067+00:00"
updated_at: "2026-07-31T12:42:12.383070+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-07-31T12:42:12.382982+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 10
---

## Definition

A single event published on the in-process EventBus. Carries a monotonic id (for frontend dedup), an EventType discriminator, an ISO timestamp, a typed data payload, and optional session/repo context. HydraFlowEvents are fanned out live to subscribers, retained in in-memory history, and persisted to an append-only JSONL log for replay; persisted IDs are advanced past historical maxima so live events never collide with replayed ones.

## Invariants

- Event IDs are monotonic and advanced past the maximum persisted ID after history load, so live events are never silently dropped by frontend dedup.
- Every HydraFlowEvent carries an EventType discriminator and an ISO-8601 timestamp; data is a plain mapping (TypedDict or model_dump).
- PIPELINE_SNAPSHOT and other EPHEMERAL_EVENT_TYPES are fanned out live-only — never retained in history nor persisted to disk.
