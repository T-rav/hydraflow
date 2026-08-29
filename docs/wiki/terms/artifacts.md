---
id: "01M15RKRY48S4039D4NPNPR965"
name: "Artifacts"
kind: "aggregate"
bounded_context: "shared-kernel"
code_anchor: "src/jsonl_ledger.py:AppendOnlyJsonlLedger"
aliases: []
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-08-28T00:00:00+00:00"
updated_at: "2026-08-28T00:00:00+00:00"
---

## Definition

The fourth layer of the PAAA governance model (ADR-0143): everything a repository has produced and kept — the software itself, plus ADRs, tests, evidence, manifests, ledgers, and recorded decisions. It answers "what evidence and memory already exist?". This is by a wide margin the richest layer in HydraFlow: `docs/arch/generated/` is regenerated every pull request, `docs/wiki/` (including these term files) carries the repo wiki, `.hydraflow/metrics/` carries the measurement streams, the append-only ledgers carry decisions and escapes, and a stamped repository carries a kernel lock. Artifacts are what the evidence collectors read to produce the normalized facts a decision layer classifies; read as input they are evidence, but evidence is not a fifth PAAA layer.

## Invariants

- Evidence is Artifacts read as input, never a fifth layer — the four layers stay four.
- Ledger records are append-only: an artifact is added or superseded, never silently rewritten.
- A conformance claim over Artifacts must be reproducible offline from a clean checkout — no claim may depend on an external service being up.
