---
id: "01KVHDB0GY6PSQPWY90DH8TNQS"
name: "Credentials"
kind: "value_object"
bounded_context: "shared-kernel"
code_anchor: "src/config.py:Credentials"
aliases: ["infrastructure credentials", "secrets bundle"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-06-20T02:21:43.838399+00:00"
updated_at: "2026-06-20T02:21:43.838402+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-06-20T02:21:43.838282+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 5
---

## Definition

A frozen value object that bundles raw infrastructure secrets — GitHub token, Sentry auth token, and WhatsApp API credentials — needed by runners and loops to authenticate with external services. Explicitly separated from HydraFlowConfig to ensure secrets never appear in domain-model serialization. Built from environment variables at startup via build_credentials() and injected as a constructor parameter into every loop or runner that calls an authenticated external API.

## Invariants

- Immutable once constructed (frozen=True); no field may be mutated after build.
- Never serialized as part of domain state — kept separate from HydraFlowConfig by design.
