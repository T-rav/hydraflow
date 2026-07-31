# ADR-0116: Prompts as a measured contract

- **Status:** Accepted
- **Date:** 2026-07-30
- **Supersedes:** none
- **Superseded by:** none
- **Related:** [ADR-0087](0087-prompt-structure-standard.md) (the standard this binds), [ADR-0093](0093-loop-fitness-as-measured-contract.md) (the pattern this reuses)
- **Enforcement:** enforced
- **Binds:** both

**Precedent:** the measured-contract tradition established for loops in ADR-0093 — a required contract per artifact, a mechanical completeness test, and a grandfather-then-shrink allowlist backfilled toward zero (source: ADR-0093, docs/superpowers/specs/2026-06-30-loop-fitness-scorecard-design.md)

**Divergence:** that tradition assumes the contract measures the artifact's *behaviour*, which is observable in operation, but a prompt's rubric score measures its *form* — statically observable and only loosely coupled to its effect — so a form floor alone rewards adding tags and edge-case boilerplate without changing what the prompt asks for; the forcing condition is the measured state at adoption (registry drifted to 25 of 65 builders unnoticed while 96% of scored prompts fail the rubric at High severity), and the rule is that the form score is inadmissible alone: it pairs with an outcome series, per-prompt setpoints bind each prompt to its own past rather than to a fleet mean, and `outcome_paired` stays false until that join lands (receipt: #10855, #10853, docs/prompt-audit-2026-04-20.md)

**Enforced by:**
pytest:tests/test_prompt_registry_completeness.py
pytest:tests/test_prompt_fitness.py
pytest:tests/test_adr_enforcement_completeness.py
pytest:tests/test_prompt_rubric_calibration.py

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

`tests/test_prompt_registry_completeness.py` asserts every prompt builder in `src/` appears in `PROMPT_REGISTRY`. Modules awaiting a fixture sit in `GRANDFATHERED`, whose size is pinned by `GRANDFATHERED_MAX` and **shrinks only** — lowering it as modules are backfilled, never raising it. This lets 30 modules land incrementally instead of as one unreviewable sweep, while closing the new-builder hole immediately.

### 3. Discovery is mechanical, not curated

The completeness test finds builders by AST walk plus naming convention (`build_*prompt*`, `compose_*prompt*`, `render_*prompt*`, and the bare `_build_prompt` / `_build_prompt_with_stats` used by phase runners), not from a hand-maintained list — because a hand-maintained list of what to check is precisely what failed here. A builder that evades the convention is **renamed to conform, not exempted.** Module-level exclusions are by named category with a stated reason; an unexplained exclusion is how a real prompt hides.

The test also guards the convention itself: if discovery stops finding the builders that are already registered, the ratchet has gone blind and fails loudly rather than passing vacuously.

### 4. ADR-0087 is Accepted, with this ADR as its enforcement vehicle

A standard that cannot be violated-and-detected is not a standard. ADR-0087 keeps ownership of the XML tag vocabulary and the 8-criterion rubric; this ADR makes it binding.

### 5. A fitness function, and floors that ratchet

A gate answers registered-or-not. Per ADR-0093 a contract also needs a **measure**, so `src/prompt_fitness.py` computes the prompt layer's scorecard: `registry_coverage`, `severity_counts`, `criterion_fail_rates`, and the allowlist size. `tests/test_prompt_fitness.py` pins every one of them at its measured value and asserts they may move only in the improving direction.

Measured at adoption (2026-07-30). The left column is the state that motivated the ADR; the right is after the backfill landed in the same PR, because a floor pinned at 30% coverage would have locked in the gap it was written to close:

| Measure | At discovery | At adoption |
|---|---|---|
| Registry coverage (per builder) | 38.8% (26 of 67 builders) | **100%** (67 of 67) |
| Prompts scored | 25 | **70** |
| Unregistered modules (`GRANDFATHERED`) | 30 | **0** |
| High-severity share | 96% (24 of 25) | **95.4%** (62 of 65) |
| Criterion 8 (edge cases named) | 84% | **52.5%** |
| Criterion 3 (XML tags) | 88% | **89.8%** |
| Criterion 1 (leads with the request) | 72% | **49.2%** |
| Criterion 4 (examples present) | — | **42.4%** |
| Criterion 7 (chain-of-thought scaffold) | — | **30.5%** |
| Criterion 5 (output contract) | 0% | **39.0%** |

The adoption column is post-backfill **and post-calibration** (§9a), so it is not comparable to the discovery column criterion by criterion. Coverage growth pushed the rates up; detector calibration pushed most of them back down and criterion 5's sharply up.

**Where coverage alone moved a rate, up was the expected direction.** Newly measured prompts were not better than the measured ones; they were simply unmeasured. Reading the rise as a regression would be exactly the error §5's derived-aggregates change exists to prevent — no prompt regressed, the denominator grew. This is also why coverage, not the fail rates, is the series to watch: the rates are a census of a population that is still being enumerated.

After calibration, two criteria still fail on more than half the fleet (3 at 89.8%, 8 at 52.5%), and criteria 3 and 7 have never been passed by any prompt — the codebase structures prompts with markdown, not XML tags, and uses no reasoning scaffolds. That is a real finding about the fleet, not a detector artifact; §9a checked. Pinning that state is not an endorsement of it — it stops the drift that produced it, and makes every subsequent improvement visible as a floor that moves. A change that worsens any per-prompt score fails the build.

**Fleet aggregates alone are insufficient, and this is the load-bearing part of the clause.** High-severity share and per-criterion fail rates are means over 25 prompts, so one prompt can degrade while another improves and the aggregate never moves — per-prompt regression is invisible. That also violates the never-compare-only-track-against-its-own-past rule this project holds elsewhere.

So the binding check is **per prompt, by name**: `PROMPT_BASELINE` in `src/prompt_fitness.py` pins the exact criteria each of the 25 scored prompts fails today, and `prompt_regressions()` reports any prompt that gains one. A prompt may only shed failures. Four assertions guard it, including two that guard the baseline itself — a scored prompt with no baseline entry is unpinned and free to rot, and a baseline looser than reality silently gives back a win the next time that prompt regresses.

This is what makes editing a prompt behave like editing tested code: the failure names the prompt and the criterion (`diff_sanity: now also fails [3] (XML tag structure)`), not a moved average.

**Fleet aggregates are asserted as derived, not pinned by hand.** An earlier revision hardcoded each criterion's fail rate. That is unstable under exactly the change this ADR wants most: registering six previously-unmeasured bad prompts raises every average without any prompt regressing, so keeping a hand-pinned number green requires editing it upward, which is indistinguishable in a diff from covering up a real regression. The aggregates are now computed from `PROMPT_BASELINE` and asserted to agree with reality exactly. Coverage growth moves them freely; a per-prompt regression is what fails the build.

Remaining part of this clause: the CI wiring of `make audit-prompts` for report regeneration. Enforcement already runs in CI via the pytest suite.

### 5a. Coverage debt is a dated commitment, not a note

A ratchet stops the gap growing. It does not make it close: an untouched allowlist stays green forever, which is the same measured-but-not-enforced defect this ADR exists to fix, one level down. `GRANDFATHERED_MAX` is therefore the ceiling *for today*, and `GRANDFATHERED_DEADLINE` (2026-09-30) is the date by which the allowlist must reach `GRANDFATHERED_TARGET` (zero). Past that date the build fails until either the backfill lands or the deadline moves in a commit that states why.

`GRANDFATHERED_BURNDOWN_ORIGIN` records where the debt started (30 modules on 2026-07-30) so the schedule can be checked rather than asserted, and `test_burndown_schedule_is_coherent` fails if the schedule is set to commit to nothing — a target at or above the origin, or a deadline before it.

### 6. Rubric score pairs with an outcome measure, and this is not optional

**The rubric measures form, not outcome.** XML tags present, request leads, edge cases named — all structural properties of the text, none of which establishes that the prompt produces better work.

A score floor without an outcome pair is therefore a direct incentive to optimise markup, and the optimiser here is not a tired human under deadline; it is a factory that will do it consistently, at scale, and report success.

So every prompt's rubric score is reported alongside its task-outcome series, from data already collected: verdict pass rate, retry and loop-back count, escape attribution (per the escape ledger), and cost per successful outcome (`prompt_telemetry.py`, `inferences.jsonl`). **A score improvement accompanied by an outcome regression is a failure, not a win**, and a claim about prompt quality citing only the score is not admissible.

**Sequencing requirement: outcome pairing lands before or with the score floors of §5, never after.**

### 7. Stated gaming failure mode

The cheapest way to raise a rubric score is to add tags and edge-case boilerplate without changing what the prompt asks for. Detection is §6's pairing plus a diff-level check that a score-improving change altered instruction content, not only markup: a change that raises the score while leaving the imperative and the constraints byte-identical is the signature.

### 8. The same gate applies to ADRs themselves

While building this, the identical gap turned up one artifact class up: `classify_adr_enforcement` has existed since ADR-0100 and its output is published to `docs/arch/generated/adr-enforcement.md`, but **nothing failed when an ADR landed without a runnable check.** Measured, not enforced — the same defect this ADR exists to close for prompts. ADR-0027 is the evidence it already drifted: no `**Enforced by:**` at all, and CI stayed green.

Measured 2026-07-30 over all 78 Accepted ADRs: **74 REAL, 3 WEAK, 1 MISSING.**

`tests/test_adr_enforcement_completeness.py` closes it, with a distinction that matters:

- **`_PROSE_ONLY`** (ADR-0025, ADR-0035, ADR-0051) are **declared permanent exceptions, not debt.** Their enforcement is genuinely a human convention — ADR-0051's own text says *"a process convention, not a runnable check"*, and 0025/0035 name review-checklist steps over symmetric field-assertion coverage and toggle-state test matching, neither of which has a proposed mechanical equivalent. Pinned at 3, each with a justification, so they read as decided rather than unfinished.
- **`_MISSING_ENFORCEMENT`** is debt and **shrinks only.** It held one entry (ADR-0027) at measurement time, pinned at 1. Trigger C of ADR-0027's own Rule 5 fired under #10867: the automated duplicate-class check landed, ADR-0027 reclassified REAL, and the allowlist emptied — the pin tightened to 0 (see `docs/adr/0027-duplicate-class-merge-artifact-pattern.md`). The ratchet only ever moves this direction; re-widening it past 0 needs a recorded decision, not an append.

Recording the difference is the point: an exception with a reason is a decision, and an exception without one is rot wearing the same clothes.

### 9. The measure is itself subject to correction, and correcting it is not a threshold change

A gate that reports failures which are not real teaches people to route around it, and a gate whose harness scores text other than what ships is not measuring the contract at all. Both turned up during the backfill and both were fixed, because a floor pinned on top of an invalid measure encodes the invalidity:

- **Harness fidelity.** `_MinimalConfig` in `scripts/audit_prompts.py` hardcoded `max_review_diff_chars = 50000` where production defaults to `15000`. The audit could therefore score a prompt containing text production would have truncated. It now defers to the real `HydraFlowConfig` defaults, inventing a value only for fields the real config does not define.
- **Detector false positives.** The criterion-3 tag matcher required a bare `<tag>`, so `<issue_content number="9812">` scored as no tags at all, and it fed criterion 6's long-context placement check as well. The criterion-4 matcher accepted `Example:` but not the house style `Example 1 — exact_dup/high:`, scoring four-example prompts as having none. Both were false *failures*, which is the dangerous direction: the gate was pushing prompt authors to strip tag attributes and renumber examples to satisfy it. Fixing them removed 4 false failures and introduced 0 new ones (criterion 3: 90.7% → 86.0%, criterion 4: 58.1% → 53.5%).

**A measure correction is distinguishable from a threshold relaxation, and the distinction must be stated in the commit.** A relaxation moves a floor to accommodate worse reality; a correction changes what reality is read as, and its before/after per-criterion delta is reported.

### 9a. The full detector calibration (2026-07-30)

Adversarial review of this PR found the two fixes above were not the whole set, and that one of them was materially overstated. Both corrections were made and the whole rubric was calibrated. **The detectors were producing false failures on natural English, which is the dangerous direction: the gate was instructing authors to make prompts worse to satisfy it.**

| Criterion | Before | After | Defect corrected |
|---|---|---|---|
| 1 leads with the request | 66.1% | **49.2%** | Strip regex had no backreference, so it matched *across* tags: a prompt wrapped in a root `<task>` reduced to `</task>` and failed. Satisfying criterion 3 broke criterion 1. `IMPERATIVE_VERBS` also omitted `determine`/`evaluate`/`analyze`, which criterion 7 already treated as decision verbs — the rubric disagreed with itself. |
| 2 specific over vague | 16.9% | **11.9%** | A literal JSON object — the most specific output spec a prompt can carry — matched no cue. |
| 3 XML tag structure | 89.8% | 89.8% | No further defect. Still zero passes across 59 prompts: a real finding, not an artifact. |
| 4 examples present | 66.1% | **42.4%** | `\bExample\b` excluded the plural, so a block of four few-shot cases under an `Examples:` heading scored as none. |
| 5 output contract stated | 5.1% | **39.0%** | A bare `do not` matched 48 of 59 prompts and was the sole carrier for 35. The celebrated 0% fail rate measured the ubiquity of an English phrase. **This rate rising is the criterion becoming informative, not 20 prompts regressing.** |
| 6 long-context placement | 8.5% | **1.7%** | Two opposite defects: a small early tag plus 18k of trailing payload passed, because a `return` *inside* the payload counted as the last instruction; and a long prompt of pure instructions failed for having no tagged block, making the criterion a duplicate of criterion 3. |
| 7 chain-of-thought scaffold | 52.5% | **30.5%** | Applicability was decided by scanning the payload, so a quoted comment saying "I will approve" made a summarisation prompt look like a decision prompt. Ten prompts demanding JSON-only output were pinned failing a criterion they could only satisfy by breaking their own parser. |
| 8 edge cases named | 91.5% | **52.5%** | The noun had to follow `if` immediately, so `If the diff is empty, return NO_CHANGES.` scored as naming no edge case. A `fallback` inside a diff under review passed. |

68 false failures removed, 21 newly detected. Criterion 8's 91.5% — one of the headline numbers this ADR was written on — was substantially a regex artifact.

**Two principles came out of this and bind going forward.** First, several criteria ask what the prompt *instructs*, and a rendered prompt also contains the issue body, the diff and the CI log; scanning the whole text answers a different question. `_instruction_prose` separates the two, preserving `<thinking>` because that is instruction, not payload. Second, over-correction is as bad as the original defect and reads as a green build: `test_every_criterion_still_discriminates` fails if any detector can no longer return both a Fail and a non-Fail, and the first attempt at criterion 6 was caught by exactly this — it went silent on 56 of 59 prompts.

`tests/test_prompt_rubric_calibration.py` pins every one of these verdicts to the input that was scored wrong, because a detector that stops detecting reports a clean bill of health it did not earn.

Markdown sections are deliberately *not* treated as context blocks for criterion 6: a `## Diff` heading has no closing delimiter, so the section runs to the next heading or to EOF and swallows the trailing instruction, scoring a correctly-ordered prompt as misplaced. A criterion that is silent beats one that is confidently wrong.

### 10. A defect class the rubric cannot see

The eight criteria score structure. They are blind to a prompt being *wrong*, and the backfill found an instance: `shape_runner` and `discover_runner` interpolated `MEMORY_SUGGESTION_PROMPT` into an f-string without `.format(context=...)`, shipping a literal `{context}` to the model. `runner_constants.py` documents the required call; four other callers honour it. All eight criteria passed this text happily, and it had been live in two loops.

`placeholder_leaks()` closes the class rather than the two instances: it strips fenced blocks, inline spans, and diff lines — where braces are legitimate, including deliberate `### P{N}` templates and f-strings inside diffs under review — and fails on a `str.format` placeholder left in prose. Zero leaks across all registered prompts after the fix.

Three tests, because a detector that stops detecting is worse than no detector: the gate itself, a test asserting it still fires on the exact 2026-07-30 defect, and a test asserting it stays quiet on the four brace-in-code shapes that would otherwise make it noise.

**The general point: a rubric bounds what it was written to look for.** Registering a prompt is worth more than the score it produces, because rendering it at all is what surfaces defects no criterion anticipated. Coverage is the load-bearing series in §5 for that reason, not the fail rates.

## Consequences

- 30 unregistered modules became **0**, and coverage is now counted **per builder rather than per module**. That change matters more than the backfill: module granularity reported 100% while five builders inside already-"covered" modules had no fixture and no score, two of them invisible that way since April. `GRANDFATHERED_MAX` is now 0, so a new builder cannot be exempted at all — and if a future subsystem genuinely needs to carry debt, raising the ceiling forces moving the deadline too, because a stale deadline with a non-empty allowlist fails the build.
- Three builders had **evaded the naming convention** and were renamed to conform per §3 rather than exempted (`agent._build_tdd_subagent_prompt`, `review_advisor.build_mid_flight_prompt`, `prompt_refiner.build_refine_prompt`). The `prompt_refiner` module-level exclusion was hiding the third behind a reason that was only true of a *different* function in the same file; function-level exclusions (`EXCLUDED_BUILDERS`) now carry reasons that have to be true of the one thing they exempt.
- New prompts cannot land unregistered; the failure mode that produced this gap closes structurally rather than by vigilance.
- The rubric gains a resting state once §5 lands, so it stops being a finding generator.
- ADR-0087 stops being a three-month-old proposal and becomes a contract.
- **The backfill paid for itself in defects, not scores.** Rendering previously-unrendered prompts surfaced: a literal `{context}` shipping to the model from two live loops (§10), a harness truncation limit 3.3× production's (§9), two rubric detectors producing false failures (§9), `render_target` unable to resolve any builder in a subpackage — which had silently made four modules unregisterable — and a report generator that drops targets in unlisted categories. None of these is a rubric criterion. This is the argument for coverage as the primary series.
- Cost: one completeness test, one CI wiring, one allowlist, and fixtures backfilled at ratchet pace. No new loop, no new subsystem.
- **Landing with this ADR:** §1-§4, plus §5's fitness function, fleet-level floors, **and the per-prompt setpoints**. **Deferred and tracked separately:** the CI wiring of `make audit-prompts` (report regeneration only — enforcement already runs in CI via pytest), and §6's outcome pairing (#10855). The ADR records the whole contract so the deferred parts are visible obligations rather than forgotten intent, and `test_form_score_is_not_a_quality_claim` fails if anyone starts treating the form score as a quality claim before §6 lands.

## Precedent / Divergence

**Precedent:** ADR-0093 (loop fitness as a measured contract) — required contract, completeness test, grandfather-then-shrink allowlist; reused wholesale rather than reinvented. `tests/test_loop_fitness_completeness.py` and `tests/test_prompt_gate_completeness.py` as the established completeness-test shape in this repo. Externally, Anthropic's published prompt-engineering guidance, from which ADR-0087's eight criteria were derived.

**Divergence:** loop fitness measures a loop's *behaviour*, observable in operation. A prompt's rubric score measures its *form*, observable statically but only loosely coupled to its effect. That asymmetry is why §6 exists: the loop contract can stand alone, whereas **the prompt contract is invalid without its outcome pair.** No prior art was located for binding a structural prompt rubric to an outcome series so the rubric cannot be gamed — structural rubrics exist, outcome telemetry exists, the binding appears to be new. Recorded as honest novelty rather than assumed practice.
