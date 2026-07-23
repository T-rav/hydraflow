# Judge independence budget + fail-visible dispatch

**Status:** proposal (2026-07-23). Closes two publicly-confessed seams in the factory's evidence path: every judge shares training gravity with the author ("the jury is siblings"), and post-verification lens dispatch fails open — when a judge is unavailable through infrastructure failure, the work passes silently.

## The gap

1. **Correlated verdicts.** Implementation and review begin in separate contexts, but author and reviewers are the same model family. When errors are habits of the weights, adding same-family lenses adds more of the same eyes: correlated failure does not look like failure, it looks like agreement with receipts. Role separation bought distance, not independence.
2. **Silent fail-open.** An infrastructure failure in post-verification lens dispatch passes the work with no verdict recorded and no alarm raised. The seam is documented; the visibility is not.

The design rule: **buy independence where errors correlate; buy votes where variance is cheap.** Same-family sampling reduces variance; only a different family (or a deterministic check) reduces correlated blindness.

## Design

### Blast-radius classes requiring an independent verdict (decided)

- Structural changes (ADR-touching, module-graph-altering)
- Security-adjacent paths (auth, secrets, prompt-assembly/trust-boundary code)
- Data migrations
- **Self-modification: any change touching the gauntlet, merge policy, gates, detectors, or this policy itself** — the highest class

Independence means: a verdict from a model family outside the implementing agent's (configured roster), or a deterministic gate where one exists for the property in question. One independent verdict is the budget; this is an added lens on classed changes, not a rewrite of the review pipeline.

### Fail-visible dispatch (decided)

- Every fail-open event (judge unavailable → work passed) becomes a ledgered record (`<data_root>/diagnostics/fail_open_ledger.jsonl`: ts, lens, PR, failure class) + a dashboard alert
- Fail-open **rate** gets a control limit; above-limit files a `hydraflow-find` issue
- **Fail-closed for the self-modification class (decided):** changes that alter the factory's own instruments cannot merge on a fail-open — a missing verdict on the machinery that produces verdicts is not a degraded pass, it is a stop. All other classes remain fail-open but ledgered and alarmed.

### Degraded mode (decided)

When no independent family is configured or reachable: non-self-modification classes proceed with the same-family verdict plus a ledgered `independence-unavailable` record (alertable rate); the self-modification class escalates to HITL instead of merging. Never silent, never wedged without a human knowing.

### Metrics and surfaces

- Percent of classed merges carrying an independent verdict
- Fail-open rate and `independence-unavailable` rate, with control limits
- Disagreement-by-family (where the independent judge dissents from the sibling verdicts — the empirical measure of how much correlated blindness the budget is catching; feeds the sampled-audit calibration picture)
- Rendered into `docs/arch/generated/gauntlet-calibration.md` alongside the sampled-audit metrics + dashboard panel

## Non-goals

No change to the ordinary (unclassed) review path, no multi-vendor orchestration beyond the configured roster, no attempt to make the container immutable — this is risk reduction on the evidence path, not absolution, and it should be described exactly that way.

## Acceptance criteria

- A synthetic PR in each blast-radius class routes to an independent judge; unclassed PRs are untouched
- A simulated dispatch failure on a classed change produces a ledger row + alert; on a self-modification change it blocks the merge and escalates
- `independence-unavailable` degraded mode is exercised and ledgered when the roster is empty
- Disagreement-by-family renders in the generated report
- The classifier that assigns blast-radius classes is itself covered by the self-modification class (it is part of the policy machinery)

## Open questions (for planning)

- Roster v1: which second family (cost/quality trade), and does a deterministic gate satisfy the budget for any class today?
- Should sustained high disagreement-by-family auto-widen the classed set (ratchet, ADR-0104 precedent), or stay a human decision?
