# Second-order vitals: detect green-while-dying

**Status:** proposal (2026-07-23). **Depends on:** the four instrument proposals (#10367 escape ledger + erosion trends, #10369 intervention tally, #10370 sampled re-audit, #10371 independence + fail-visible). This is their capstone: the monitor for the one failure state the factory publicly stakes itself against — **the gauntlet green while the codebase curdles underneath**.

## The gap

First-order health is watched (`factory_health`, `health_monitor_loop`, CI pass rates, merge throughput). The four new instruments each watch one second-order dimension and file their own findings. But green-while-dying is not visible in any single series — it is a **joint** condition: primary signals healthy while several independent second-order signals drift adverse together. Correlated adverse drift across independent instruments is simultaneously the hardest signal to dismiss and the exact shape of the failure the skeptics predict. Nothing computes it.

In control-theory terms this is residual monitoring under analytical redundancy: the primary gates are the plant's own claim about its health; the second-order instruments are independent estimates; a sustained residual between them is the fault signal.

## Design

### Inputs (read-only, from the instrument ledgers/series)

1. Escapes per 100 merges (escape ledger)
2. Erosion trends: change-spread, concept-scatter, duplication density
3. Correction-class intervention rate (tally; `approval` excluded by design)
4. Audit disagreement rate (sampled re-audit)
5. Fail-open + `independence-unavailable` rates (independence proposal)

Plus the primary-health gate: CI pass rate and merge throughput within normal bands (the "green" precondition — this monitor only speaks to divergence, not to ordinary red).

### The divergence condition (decided)

- Each input series carries its own control limits (Shewhart individuals chart per series; baselines primed from the series' own history once ≥1 full window exists)
- **Watch**: primary health green AND ≥2 of the 5 input families above their control limits, sustained for 2 consecutive evaluation windows
- **Diverging**: primary health green AND ≥3 families sustained adverse — the green-while-dying verdict
- Sustained-window + k-of-n is the anti-flap design; single-series spikes belong to that instrument's own finding path, never to this monitor

### Output (decided)

- One **vitals verdict** — `green | watch | diverging` — rendered on the dashboard and in `docs/arch/generated/second-order-vitals.md`, with the contributing series and their residuals shown (the verdict must always be explainable from its inputs on the same page)
- `watch` → dashboard state change only (no issue; observing is the point)
- `diverging` → files ONE highest-priority `hydraflow-find` and escalates HITL directly. This is the single alarm in the factory that is never batched, deduplicated away, or cooled down — by construction it can only fire after multi-family, multi-window persistence, so a firing is load-bearing
- Verdict history is itself an append-only series (`<data_root>/diagnostics/vitals.jsonl`) so "how long were we in watch" is answerable

### Loop shape and self-reference (decided)

`SecondOrderVitalsLoop`: read-only ADR-0029 caretaker, Pattern B. It computes and reports; it never remediates. It degrades honestly: with instruments not yet built or series too young for baselines, the verdict is `green (n-of-5 instruments reporting)` — partial coverage is displayed, never silently treated as full. And it is explicitly **self-modification class under the independence proposal**: changes to this loop, its thresholds, or its input wiring require an independent verdict and fail closed. The monitor for green-while-dying must not be quietly editable by the machinery it monitors.

## Non-goals

No remediation, no gating of ordinary merges, no fusion of first-order health (existing loops own that), no ML anomaly detection in v1 — control limits and counting are legible, and legibility is a feature in the instrument that has to be trusted when it fires.

## Acceptance criteria

- Synthetic series driving 2-of-5 and 3-of-5 sustained adverse states produce `watch` and `diverging` respectively; single-family spikes and one-window blips produce neither
- A `diverging` verdict files exactly one highest-priority finding and one HITL escalation, once per episode (episode = until the condition clears)
- Partial-coverage display verified with instruments absent
- The generated report shows, for any verdict, the exact contributing series and residuals
- The loop's own files are classed self-modification (verifiable against the independence policy's classifier)

## Open questions (for planning)

- Evaluation window length (weekly vs. per-100-merges — align with the instrument denominators?)
- Should `watch` state older than N windows auto-escalate even below the 3-family bar?
- Does the verdict belong on the public architecture site as well as the dashboard (the book's falsification ledger argues yes)?
