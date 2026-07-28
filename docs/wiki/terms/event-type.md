---
id: "01KYM003P7D6GN4KSS1X9RBEXQ"
name: "EventType"
kind: "value_object"
bounded_context: "shared-kernel"
code_anchor: "src/events.py:EventType"
aliases: ["event category", "event kind"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-28T09:13:23.911808+00:00"
updated_at: "2026-07-28T09:13:23.911810+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-07-28T09:13:23.911769+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 10
---

## Definition

Closed enumeration of the event categories the orchestrator publishes through the EventBus. Each value names a distinct kind of state change or observable occurrence — phase transitions, worker updates, PR lifecycle events, HITL escalations, CI checks, fitness updates, ADR conformance changes, and adversarial-pipeline stages — that subscribers (dashboard, loops, persistence) react to. Engineers add a new member whenever a new class of happening enters the system.

## Invariants

- Members are append-only; existing string values are never renamed because persisted JSONL event logs depend on stable representations.
- A designated subset (EPHEMERAL_EVENT_TYPES, e.g. PIPELINE_SNAPSHOT) is live-only — fanned out to connected subscribers but never retained in in-memory history nor persisted to the on-disk log.
