"""Intervention-tally instruments — the attention-side telemetry (#10369).

Cost telemetry answers "what does the factory spend"; nothing answers "what
does the human spend." This package is the attention-side twin of the escape
ledger (#10367): it records every human TOUCH on the factory — steering
directives, HITL escalation lifecycles, dashboard control actions, ``/hf``
CLI admin commands — classifies each into a fixed v1 taxonomy, and trends it
as a rate (interventions per 100 merges, per-loop rate, loops-per-governor).

Layered like the sibling ``escape`` package (mirror-the-style, don't
cross-import except for the deliberately-shared per-100-merges denominator):
``models`` (value objects + the fixed taxonomy enum), ``classify`` (pure
mechanical source→class mapping + a cheap-LLM verdict parser for free-text
steering), ``sources`` (thin adapters that materialize raw signals from the
persisted event log + steering state), ``ledger`` (append-only JSONL store),
``metrics`` (pure rate rollups — the per-100-merges denominator is IMPORTED
from ``escape`` so it can never diverge), ``report`` (markdown render).

The consuming caretaker is ``intervention_tally_loop.InterventionTallyLoop``
— a read-only ADR-0029 Pattern-B sensor that senses + records, and NEVER
gates, blocks, or files fix PRs. Classification never blocks the action it
observes; low-confidence free-text rows keep the raw text for later re-label.
"""
