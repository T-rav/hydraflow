---
id: "01KTX0X7RK9NPDNYRPZ58BVT9J"
name: "ADRCouncilReviewer"
kind: "service"
bounded_context: "caretaker"
code_anchor: "src/adr_reviewer.py:ADRCouncilReviewer"
aliases: ["adr council reviewer", "council reviewer"]
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K3"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K2"}, {"kind": "depends_on", "target": "01KVHDB0GY6PSQPWY90DH8TNQS"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-06-12T04:19:40.947529+00:00"
updated_at: "2026-06-20T07:11:08.058010+00:00"
updated_at: "2026-06-20T05:03:15.326246+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-06-12T04:19:40.947404+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 1
---

## Definition

ADRCouncilReviewer is the domain service that runs multi-agent council review sessions on proposed Architecture Decision Records. It scans the ADR directory for files marked Status: Proposed, gates each candidate through ADRPreValidator, detects near-duplicate ADRs via similarity scoring, orchestrates multi-round council voting, and routes each outcome to acceptance, rejection, escalation, or duplicate-flagging. ADRReviewerLoop delegates all review logic to this service on every polling cycle.

## Invariants

- CreditExhaustedError and AuthenticationError propagate out of the review batch rather than being swallowed per-item, so BaseBackgroundLoop can pause on a fatal billing signal.
- Every ADR that reaches Accepted status is guaranteed to carry an **Enforced by:** line (injected as '(none)' if absent) before it is written back.
- Pre-validation must pass before a council session is started; a failing ADR is routed and counted separately without blocking the rest of the batch.
