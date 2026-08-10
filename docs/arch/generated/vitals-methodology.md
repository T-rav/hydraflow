# Vitals Methodology (ADR-0133)

How the vitals instrument fleet is read *as evidence*: the widened-limit multiplier that holds the fleet's family-wise false-alarm budget, the minimum detectable effect per instrument, and which metrics belong on a time-between-events chart. Deterministic — a function of the registered series set and the ADR-0133 arithmetic alone. **No live threshold is changed by this surface**; it is the readiness signal for the eventual widened-limit migration.

## Widened control limit — the registered second-order fleet

- **Registered series (charts evaluated together):** 8
- **Family-wise budget:** 5% / month (Bonferroni, two-sided)
- **Widened multiplier L:** 3.000σ (classic Shewhart is 3.0σ)
- **Status:** _at the 3σ floor_ — 8 charts at a 5% budget computes a limit looser than 3σ, so the floor holds it at 3.0σ. The fleet does not need widening yet; the verdict's live 3σ limit is already correct.

## Widening curve (readiness projection)

Where the 3σ floor lifts as the instrument fleet grows:

| Registered charts | Widened L | Above 3σ? |
|------------------:|----------:|:---------:|
| 8 ← current | 3.000σ | floored |
| 15 | 3.000σ | floored |
| 19 | 3.008σ | yes |
| 30 | 3.144σ | yes |
| 50 | 3.291σ | yes |
| 70 | 3.384σ | yes |

## Minimum detectable effect (per instrument, per window)

Baseline events a rate metric needs to detect a given rate ratio at α=0.05, 80% power. A metric whose window volume is below its row cannot evidence that effect — chart it as time-between-events instead of a rate.

| Rate ratio to detect | Baseline events needed |
|---------------------:|-----------------------:|
| 2× | 11 |
| 1.5× | 39 |
| 1.25× | 141 |
| 1.1× | 824 |
| 0.9× | 745 |
| 0.75× | 109 |
| 0.5× | 23 |

## Scarce-event metrics (time-between-events candidates)

A per-window count that is usually zero (escapes on a low-merge repo) has no power as a rate chart — a monthly 'flat' reading on ~1.5 events/month is not evidence. These move to a Benneyan g/t-chart on the interval between events:

- **escapes per window** (`escapes`) — escapes are rare by design; a g-chart on merges-between-escapes (+ the consecutive-zeros run rule) reads deterioration a rate chart's 0-pinned lower limit cannot.


<!-- arch:generated -->
