# ADR-0130: Prompt outcome pairing — make the form rubric ungameable before a floor

- **Status:** Proposed
- **Date:** 2026-08-05
- **Related:** [ADR-0087](0087-prompt-structure-standard.md) (the 8-criterion form rubric this pairs an outcome to) and [ADR-0116](0116-prompts-as-a-measured-contract.md) §6 (form-not-outcome — a score is not admissible on its own; the rule this ADR encodes); requirement 6 of #10853 (must land before or with any score floor); #10840 (the counter-metric policy this applies to the largest measured surface); #10369 (model-version reset markers — comparisons reset at a version boundary); #10838 (minimum detectable effect — report it rather than charting noise); #10367 (`src/escape/ledger.py`, the escape-attribution outcome source); `prompt_fitness.fitness_summary` (the `outcome_paired` flag this fills)
- **Enforcement:** enforced
- **Enforced by:** `pytest:tests/test_prompt_outcome_pairing.py`
- **Binds:** factory
- **Addresses:** #10855 (prompt outcome pairing — join rubric scores to task outcomes before any score floor lands)

> **This is a Proposed ADR — a design ruling for decision, not an accepted commitment.** It records the rule and the gaming detector that ship today, and — as #10855 explicitly requires — the honest limitation that blocks the full builder-scoped outcome join. Accept, amend, or reject.

## Context

The 8-criterion ADR-0087 rubric (`prompt_fitness`) measures the **form** of a prompt: XML tags present, request leads, edge cases named. None of that establishes that the prompt produces better work. A score *floor* on a form metric creates a direct incentive to optimise markup — and the optimiser is not a careless human under deadline, it is a factory that will do it consistently, at scale, and report success. **Goodhart with the factory holding the pen**: the dashboard would show rising prompt quality while results degraded. ADR-0116 §6 already forbids treating a form score as a quality claim on its own; #10855 asks for the machinery that makes the pairing real, and insists it land *before or with* any floor, never after.

## Decision

Ship `src/prompt_outcome_pairing.py` — a pure engine with the two guards that make a form score admissible, plus an honest account of the join that is not yet possible.

1. **The rule** (`pairing_verdict`): a score improvement accompanied by a **quality** regression (pass rate down, or retries / escapes up, past a materiality threshold) is `SCORE_UP_OUTCOME_DOWN` — a failure, not a win. A prompt is compared only against **its own prior baseline** (never a cross-prompt league table — the never-compare-teams rule) and only within a single model version (`MODEL_VERSION_BOUNDARY` when the two sides straddle an upgrade, #10369). Too few resolved outcomes → `INSUFFICIENT_DATA` with a reported minimum detectable effect (#10838), never a verdict from noise. Cost is reported as efficiency, not folded into the quality trigger.

2. **Gaming-failure-mode detection** (`detect_markup_only_gain`): the cheapest way to raise the form score is to add tags and edge-case boilerplate without changing the request. The detector strips structural markup to the prompt's **instruction content** (imperative + constraints) and flags a score-improving change whose instruction content is byte-identical — a score that rose while the request did not. Surfaced, not celebrated.

## The honest limitation (required by #10855)

Attribution is confounded, and the confounding is structural, not merely noisy: **the rubric keys a prompt *builder by name*, and no record anywhere links a builder to the outcomes of the work it produced.** Every outcome series is keyed elsewhere —

| Outcome series | Key it carries | Builder link? |
|---|---|---|
| verdict pass rate / retries (`ConvergenceLedger`) | `issue_number`, `stage` | no |
| escape attribution (`escape_ledger.jsonl`) | `originating_pr`, `merge_sha` | no |
| cost / tokens (`inferences.jsonl`) | `source` (loop), `issue_number`, `pr_number` | no |

So a *builder-scoped* outcome series cannot be computed today; the only structurally sound join axis is `issue_number`. Consequently **`prompt_fitness.outcome_paired` stays `False`** — this ADR does not flip it, because a form score still cannot be attributed to a specific builder's outcomes. Closing that gap needs a *prompt-of-record* field (new capture, contradicting #10855's "this is a join" premise) recorded where the work is produced; that is filed as the follow-up. The **rule** and the **gaming detector**, which compare a prompt against its own two versions/baselines, need no such join and are live now.

**Divergence (lineage):** no prior art was located for scoring generative-system prompts against an outcome series so the form rubric cannot be gamed. Structural prompt rubrics exist and outcome telemetry exists; binding them appears to be genuine novelty, flagged as such rather than assumed practice.

## Consequences

- The two guards that need no join ship today and are the concrete anti-Goodhart mechanism a score floor requires: a floor may not be justified by a score gain that the rule finds inadmissible or the detector finds markup-only.
- The full builder-scoped outcome trend is **blocked on a missing data field**, stated plainly rather than faked. `outcome_paired` remains an honest `False`.
- Because instruction-content extraction is deliberately aggressive (it strips exactly the formatting the rubric rewards), it answers "did the request change?" well but is not a general prompt-diff; it is scoped to the gaming check.
