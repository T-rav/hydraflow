# Intervention tally: attention-side telemetry

**Status:** proposal (2026-07-23). **Companion to:** the escape ledger + erosion trends proposal (#10367). Cost telemetry answers "what does the factory spend"; nothing answers "what does the human spend." This is the attention-side twin.

## The gap

Human touches on the factory are sensed in fragments — steering directives (`human_steering_loop`, ADR-0099 #4), HITL escalation lifecycles, dashboard control actions, approval records — but nothing classifies them, counts them as a rate, or trends them. Three consumers need that signal:

1. **Trust calibration**: intervention rate per loop/workflow is the signal that says which loops have earned autonomy and where human sampling should concentrate. It resets on model upgrades; today those resets are invisible.
2. **Span of control**: loops-per-governor — how many concurrent worker loops one human governs — is the headline measure of how much engineering the factory's primitives have absorbed. It is currently an anecdote, not a metric.
3. **The falsification set**: escape rate (detected), audit disagreement (undetected estimate), and intervention rate (human load) together answer whether autonomy is real or subsidized by invisible babysitting.

## Design

### Intervention taxonomy (v1, fixed enum — decided)

- `objective-correction` — human redirected the goal or plan (not the implementation)
- `unstick` — loop wedged, looping, or stalled; human intervened to free it
- `instruction-violation` — the system did something it was told not to do; human corrected
- `quality-override` — bad output passed the gates; human caught it downstream
- `steering-nudge` — routine mid-flight directive (existing steering grammar)
- `approval` — routine HITL approve/deny with no correction content (lightest class, counted separately so it never inflates the correction rate)

### Sources (v1)

Steering directives (already parsed to `SteeringState`), HITL escalation lifecycle events (raised, resolved, resolution class), dashboard control-route actions, `/hf` CLI administrative commands. Out of v1 scope: manual git surgery outside the factory's surfaces (note in report as a known blind spot).

### Classification (decided)

Mechanical mapping where the source implies the class (escalation resolution codes, control-route action types). LLM classification (cheap model) only for free-text steering comments, with `confidence` recorded; low-confidence rows keep the raw text for later re-label. Classification never blocks the action itself.

### Storage and loop shape

Append-only `<data_root>/diagnostics/intervention_ledger.jsonl` (fields: `ts, source, class, confidence, loop_or_workflow, issue_or_pr, model_version_context, ref, notes`). `InterventionTallyLoop`: read-only ADR-0029 caretaker, Pattern B, cursor-primed like `ErosionMetricsLoop` — it aggregates records the factory already emits; it never gates, blocks, or files fix PRs.

### Metrics and surfaces

- **Interventions per 100 merges** (same denominator as the escape ledger, deliberately) — rolling 30-day and monthly, split by class; `approval` reported separately
- **Per-loop intervention rate** — the trust table: which loops earned autonomy
- **Loops-per-governor** — median concurrently-active worker loops divided by daily correction-class interventions
- **Model-version annotations** on every trend (from runtime config history) so trust resets are visible instead of mysterious
- Regenerated `docs/arch/generated/intervention-tally.md` + dashboard panel

## Non-goals

No enforcement, no per-human attribution beyond "a human" (single-operator today; the field exists but is not surfaced), no retroactive classification of history before cursor-prime (optional explicit backfill command may be a follow-up).

## Acceptance criteria

- Each v1 source produces ledger rows with class + confidence; free-text steering comments classify with recorded confidence
- Interventions per 100 merges, per-loop rates, and loops-per-governor render in the generated report and dashboard
- Model-version change markers appear on trend series
- A synthetic flood of steering comments does not produce unbounded LLM classification spend (batch + budget)
- Fresh install primes cursors with no back-analysis

## Open questions (for planning)

- Should `quality-override` rows auto-cross-link to the escape ledger when both fire on the same defect?
- Is per-loop trust worth surfacing as an explicit autonomy tier (informational), or does the table suffice?
