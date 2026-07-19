---
id: "01KVJPGB886SYJA08BNCWTAC28"
name: "ADRPreValidator"
kind: "service"
bounded_context: "caretaker"
code_anchor: "src/adr_pre_validator.py:ADRPreValidator"
aliases: ["adr pre-validator", "adr structural validator"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-06-20T14:21:10.280395+00:00"
updated_at: "2026-06-20T14:21:10.280399+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-06-20T14:21:10.280289+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 1
---

## Definition

A service that validates ADR structure before submission to the ADRCouncilReviewer, catching structural defects early in the review pipeline. Checks include: status field presence and validity, required section presence and non-emptiness (Context, Decision, Consequences), ADR number collisions, supersession integrity, volatile line citations, stale 'requires amending' notes, bare ADR references lacking title annotations, source-symbol references against the live repo, and cross-reference title accuracy. Returns an ADRValidationResult that distinguishes auto-fixable issues from blocking ones, allowing the council to skip reviews for trivially malformed drafts.

## Invariants

- Runs all structural checks in a single `validate()` call and returns an ADRValidationResult — never raises on malformed input.
- Issues are classified as fixable or non-fixable; `has_fixable_only` lets callers auto-repair before escalating to the council.
- Cross-ADR checks (number collision, supersession, cross-reference titles) are skipped when `all_adrs` is not supplied, so single-ADR validation is always safe.
