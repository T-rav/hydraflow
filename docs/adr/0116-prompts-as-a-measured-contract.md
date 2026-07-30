# ADR-0116: Prompts as a measured contract

- **Status:** Accepted
- **Date:** 2026-07-30
- **Supersedes:** none
- **Superseded by:** none
- **Related:** [ADR-0087](0087-prompt-structure-standard.md) (the standard this binds), [ADR-0093](0093-loop-fitness-as-measured-contract.md) (the pattern this reuses)
- **Enforcement:** enforced
- **Binds:** both

**Enforced by:**
pytest:tests/test_prompt_registry_completeness.py
pytest:tests/test_prompt_fitness.py

## Context

The prompt layer is already a subsystem with five organs, built incrementally and never named as one:

| Organ | Where it lives | State at 2026-07-30 |
|---|---|---|
| Registry | `PROMPT_REGISTRY` in `scripts/audit_prompts.py` (name, builder path, fixture, category, source line) | **25 entries, 65 builders** |
| Standard | ADR-0087 (XML tag vocabulary, 8-criterion rubric) | **`Proposed` since 2026-04-21** |
| Mechanical scoring | `score_*` in `scripts/audit_prompts.py`; `make audit-prompts` renders every fixture, scores it, regenerates the report | manual target, not in CI, no floor |
| Assembly + governance gate | `prompt_builder.py`; `prompt_gate.py` (CH-6, #9734 — the one choke point every assembly → spawn path consults: data-class classification, redaction, backend allowlist, fail-closed) | shipped, enforced |
| Telemetry | `prompt_telemetry.py` → hash-chained `inferences.jsonl` (CH-1, #9729) | shipped |

Measured on 2026-07-30: **65 prompt builders across 43 modules; 30 of those modules have no registry entry at all.** The registry was built in April against 26 prompts. The factory grew past it and nothing noticed, because nothing asserted the invariant.

So the defect is not missing machinery. It is that the rubric is a **finding generator rather than a regulator**: real instruments, no obligation, no resting state. A prompt can be added with no fixture, no registry entry and no score, and no gate objects.

ADR-0093 already solved this shape for loops — a required contract, a completeness test, and a grandfather-then-shrink allowlist. This ADR is that pattern applied to prompts.

## Decision

### 1. Prompts are a governed artifact class, not strings in code

Every model-bound prompt has a registry entry, a rendered fixture, and a score. The prompt layer is named as a subsystem, with the five organs above as its parts.

### 2. Registry completeness is enforced by a ratchet

`tests/test_prompt_registry_completeness.py` asserts every prompt builder in `src/` appears in `PROMPT_REGISTRY`. Modules awaiting a fixture sit in `_GRANDFATHERED`, whose size is pinned by `_GRANDFATHERED_MAX` and **shrinks only** — lowering it as modules are backfilled, never raising it. This lets 30 modules land incrementally instead of as one unreviewable sweep, while closing the new-builder hole immediately.

### 3. Discovery is mechanical, not curated

The completeness test finds builders by AST walk plus naming convention (`build_*prompt*`, `compose_*prompt*`, `render_*prompt*`, and the bare `_build_prompt` / `_build_prompt_with_stats` used by phase runners), not from a hand-maintained list — because a hand-maintained list of what to check is precisely what failed here. A builder that evades the convention is **renamed to conform, not exempted.** Module-level exclusions are by named category with a stated reason; an unexplained exclusion is how a real prompt hides.

The test also guards the convention itself: if discovery stops finding the builders that are already registered, the ratchet has gone blind and fails loudly rather than passing vacuously.

### 4. ADR-0087 is Accepted, with this ADR as its enforcement vehicle

A standard that cannot be violated-and-detected is not a standard. ADR-0087 keeps ownership of the XML tag vocabulary and the 8-criterion rubric; this ADR makes it binding.

### 5. A fitness function, and floors that ratchet

A gate answers registered-or-not. Per ADR-0093 a contract also needs a **measure**, so `src/prompt_fitness.py` computes the prompt layer's scorecard: `registry_coverage`, `severity_counts`, `criterion_fail_rates`, and the allowlist size. `tests/test_prompt_fitness.py` pins every one of them at its measured value and asserts they may move only in the improving direction.

Measured at adoption (2026-07-30), and the numbers are why this ADR exists:

| Measure | Value |
|---|---|
| Registry coverage | **30.2%** (13 of 43 modules) |
| High-severity share | **96%** (24 of 25 scored) |
| Criterion 3 (XML tags) fail rate | **88%** |
| Criterion 8 (edge cases named) fail rate | **84%** |
| Criterion 1 (leads with the request) fail rate | **72%** |
| Criterion 5 (output contract) fail rate | 0% |

Three of the eight criteria fail on most prompts. Pinning that state is not an endorsement of it — it stops the drift that produced it, and makes every subsequent improvement visible as a floor that moves. A change that worsens any measure fails the build.

The per-prompt setpoint (a minimum score each prompt must hold, so the rubric goes quiet inside the band) and the CI wiring of `make audit-prompts` are the remaining part of this clause; the fleet-level floors land now.

### 6. Rubric score pairs with an outcome measure, and this is not optional

**The rubric measures form, not outcome.** XML tags present, request leads, edge cases named — all structural properties of the text, none of which establishes that the prompt produces better work.

A score floor without an outcome pair is therefore a direct incentive to optimise markup, and the optimiser here is not a tired human under deadline; it is a factory that will do it consistently, at scale, and report success.

So every prompt's rubric score is reported alongside its task-outcome series, from data already collected: verdict pass rate, retry and loop-back count, escape attribution (per the escape ledger), and cost per successful outcome (`prompt_telemetry.py`, `inferences.jsonl`). **A score improvement accompanied by an outcome regression is a failure, not a win**, and a claim about prompt quality citing only the score is not admissible.

**Sequencing requirement: outcome pairing lands before or with the score floors of §5, never after.**

### 7. Stated gaming failure mode

The cheapest way to raise a rubric score is to add tags and edge-case boilerplate without changing what the prompt asks for. Detection is §6's pairing plus a diff-level check that a score-improving change altered instruction content, not only markup: a change that raises the score while leaving the imperative and the constraints byte-identical is the signature.

## Consequences

- 30 unregistered modules become a shrinking, tracked series rather than an invisible gap.
- New prompts cannot land unregistered; the failure mode that produced this gap closes structurally rather than by vigilance.
- The rubric gains a resting state once §5 lands, so it stops being a finding generator.
- ADR-0087 stops being a three-month-old proposal and becomes a contract.
- Cost: one completeness test, one CI wiring, one allowlist, and fixtures backfilled at ratchet pace. No new loop, no new subsystem.
- **Landing with this ADR:** §1-§4, plus §5's fitness function and fleet-level ratcheting floors. **Deferred and tracked separately:** §5's per-prompt setpoints and the CI wiring of `make audit-prompts`, and §6's outcome pairing. The ADR records the whole contract so the deferred parts are visible obligations rather than forgotten intent, and `test_form_score_is_not_a_quality_claim` fails if anyone starts treating the form score as a quality claim before §6 lands.

## Precedent / Divergence

**Precedent:** ADR-0093 (loop fitness as a measured contract) — required contract, completeness test, grandfather-then-shrink allowlist; reused wholesale rather than reinvented. `tests/test_loop_fitness_completeness.py` and `tests/test_prompt_gate_completeness.py` as the established completeness-test shape in this repo. Externally, Anthropic's published prompt-engineering guidance, from which ADR-0087's eight criteria were derived.

**Divergence:** loop fitness measures a loop's *behaviour*, observable in operation. A prompt's rubric score measures its *form*, observable statically but only loosely coupled to its effect. That asymmetry is why §6 exists: the loop contract can stand alone, whereas **the prompt contract is invalid without its outcome pair.** No prior art was located for binding a structural prompt rubric to an outcome series so the rubric cannot be gamed — structural rubrics exist, outcome telemetry exists, the binding appears to be new. Recorded as honest novelty rather than assumed practice.
