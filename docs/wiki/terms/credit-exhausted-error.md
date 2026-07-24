---
id: "01KY9SS1BTZMWRAW2VRS3WPBCG"
name: "CreditExhaustedError"
kind: "domain_event"
bounded_context: "shared-kernel"
code_anchor: "src/subprocess_util.py:CreditExhaustedError"
aliases: ["billing-limit signal"]
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K5"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-24T10:12:16.378615+00:00"
updated_at: "2026-07-24T10:12:16.378618+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-07-24T10:12:16.378571+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 6
---

## Definition

CreditExhaustedError signals that a gh/git/claude subprocess call failed because the underlying API billing account (Anthropic, or a one-shot OpenAI-compatible backend such as openrouter/zai/kimi) has run out of credits. It carries the billing-provider identity and an optional resume_at UTC reset time so the orchestrator can scope the resulting pause to only the loops routed to that provider — a Claude cap must not halt z.ai/kimi background workers and vice-versa. Every subprocess-spawning runner's broad except block must route this exception through reraise_on_credit_or_bug so it halts attempt-budget consumption instead of being silently swallowed and retried against an exhausted billing signal.

## Invariants

- Subprocess-spawning runners MUST call reraise_on_credit_or_bug(exc) in their broad except block, or CreditExhaustedError is silently eaten and the loop burns attempt budget against an exhausted billing signal.
- Carries provider (defaulting to "anthropic") so the orchestrator scopes the credit pause to only loops routed to the same provider, never cross-halting other providers.
- resume_at, when parseable from subprocess error output, tells the orchestrator when credits are expected to reset.
