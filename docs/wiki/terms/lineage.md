---
id: "01KYJ33WCCSSDWGE44CQ31ZN9D"
name: "Lineage"
kind: "value_object"
bounded_context: "shared-kernel"
code_anchor: "src/adr_index.py:ADR"
aliases: []
related: [{"kind": "depends_on", "target": "01KVJPAQ8987YPSRSWWWJJTBSG"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-27T00:00:00+00:00"
updated_at: "2026-07-27T00:00:00+00:00"
---

## Definition

The named engineering tradition a control-plane ADR inherits (its **Precedent**) together with the forced break it takes from that tradition (its **Divergence**, which must cite a receipt). Lineage makes the ADR corpus separate inherited engineering from genuine novelty: unforced invention is a defect, forced invention has a named forcing condition and a receipt. The two optional single-line fields are defined by ADR-0113, parsed by the pure functions in scripts/hydraflow_audit/lineage.py, and enforced on the control-plane ADR set by the P1.17 audit check. Anchored on the parsed ADR record the fields annotate.

## Invariants

- A control-plane ADR carries at least one lineage line — a Precedent or a Divergence (P1.17, ADR-0113).
- Every Divergence cites a receipt (an ADR, incident, #issue, or docs path); a receipt-less Divergence is a defect — unforced invention.
- A Precedent names a real, citable tradition; retrofitted branding fails review.
