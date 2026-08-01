# ADR-0117: Observed prompt coverage — the denominator is measured, not inferred

- **Status:** Accepted
- **Date:** 2026-07-31
- **Supersedes:** none
- **Superseded by:** none
- **Related:** [ADR-0116](0116-prompts-as-a-measured-contract.md) (the contract this completes), [ADR-0087](0087-prompt-structure-standard.md) (the rubric being applied)
- **Enforcement:** enforced
- **Binds:** both

**Precedent:** ADR-0116's measured-contract pattern for prompts — a registry, a completeness ratchet, and a fitness scorecard — plus the CH-6 prompt gate (#9734), already established as the one choke point every assembly → spawn path consults (source: ADR-0116, src/prompt_gate.py)

**Divergence:** ADR-0116 counts coverage against a denominator *inferred* from a naming convention, and a denominator you infer is one you can be wrong about without noticing; this ADR takes the denominator from what the factory actually sent through the gate, which makes a prompt's existence an observation rather than a guess, and the reconciliation's own liveness part of the result rather than an assumption (receipt: #10857, #10858, tests/test_prompt_observatory.py)

**Enforced by:**
pytest:tests/test_prompt_observatory.py

## Context

ADR-0116 closed the prompt layer's contract and reported **100% coverage — 67/67 builders, 70 prompts scored.** That number is true and it is narrower than it sounds.

Coverage is counted against `prompt_fitness.discovered_builders()`, an AST walk of `src/` matching function names against `_BUILDER_NAME`. Verified on 2026-07-31 by adding real prompt builders to `src/` and running the gates:

| what was added | detected? |
|---|---|
| `build_zz_proof_prompt()` | **yes** — ratchet went red, named the builder |
| `make_prompt()` | **no** — all 11 gates green |
| `assemble_instructions()` | **no** — all 11 gates green |

Three real builders had in fact been evading it (`agent._build_tdd_subagent_plan`, `review_advisor.format_mid_flight_for_prompt`, `prompt_refiner.assemble_refine_context`) and were renamed to conform. That fixed the instances and not the mechanism. Separately, 18 Markdown templates under `prompts/auto_agent/` are model-bound prompts that are not Python functions at all, so the AST walk cannot see them in principle (#10858).

**The defect is structural: an inferred denominator cannot report what it fails to enumerate.** A gate whose scope is defined by a regex reports full coverage of the set it happens to match, and says nothing about the set it does not. That is the same class of error as ADR-0116 §9's measurement bugs — a measure reporting better news than reality — one level further out.

## Decision

### 1. The denominator comes from the gate, not from names

Every assembled prompt passes `prompt_gate.gate_prompt` before reaching a backend. At that point "this text is about to be sent to a model" is a **fact**, not a naming guess. `prompt_observatory.observe` records the prompt's *shape* there, before any data-class branching so the record covers unregulated prompts too — which the gate's own audit stream does not see.

This makes coverage answerable in the only way that cannot be evaded: *of the prompts the factory actually sent, how many does the eval suite score?*

### 2. Records carry no prompt content

The gate's audit stream holds "counts and pattern NAMES only" because regulated-class content flows through it. The observation stream inherits that rule without exception.

A record holds a shape id, source, tool, counts, and **SHA-256 digests** of structural anchors — never the anchors themselves. The digests are enough to match, and cannot be read back into the text. This matters because anchor extraction cannot perfectly separate a builder's literal from wrapped payload, so the digest is not an optimisation, it is the safety property. `test_record_carries_no_prompt_content` pins it against a prompt carrying a name, SSN, email and API key.

### 3. A shape is structural, and must not move with the payload

Anchors are Markdown headings, bolded labels, section tags, and the builder's own literal instruction lines, each normalized with digits, URLs, paths, quoted strings and code spans removed before hashing.

Two decisions came out of measurement rather than taste:

- **Headings alone are too thin.** Over the 70 registered fixtures, 11 carried fewer than three anchors and 5 carried none, hashing identically. Adding instruction lines took it to **70 distinct shapes, 0 collisions**.
- **`**Label**: value` lines are excluded.** They mix the literal with the interpolated value, so payload changes moved the shape — the one thing a shape must not do. The label is already captured separately.

### 4. Jaccard, not containment — checked, not assumed

Production renders include optional sections a fixture lacks, so matching is by resemblance rather than equality. Containment (`|A∩B| / min(|A|,|B|)`) looks like the better metric for that and **is not**:

| | fixture + 40 optional anchors | worst unregistered template |
|---|---|---|
| Jaccard | 0.733 | **0.402** |
| Containment | 1.000 | **1.000** |

Containment tolerates optional sections better and lets a *small unregistered prompt whose anchors all sit inside a large registered one* score 1.000 — a total false negative. Jaccard's union denominator is exactly what prevents that. The apparent improvement was a masking bug.

Measured separation with Jaccard: same builder across payloads **0.97–0.98**; the 17 unregistered `auto_agent` templates **median 0.006**; the 2 registered ones **1.000**. At threshold 0.5 that is **17/17 detected, 0 false positives**.

### 5. The threshold ranks findings; it does not decide them

A tunable threshold as the verdict is a knob, and a knob gets turned until the alarm stops. This repo already rejects that shape for `GRANDFATHERED`, `EXCLUDED_BUILDERS` and `PLACEHOLDER_LEAK_EXEMPT`.

So resemblance **ranks and annotates**; the pass/fail authority is `ACKNOWLEDGED_SHAPES`, keyed by shape with a written reason, pinned by size, and guarded by a test that fails on an unexplained entry. A finding is cleared by recording *why it is acceptable*, never by moving a number.

### 6. Absence of findings is not evidence of coverage

Observation is best-effort and must never block a send — a measurement failure cannot be allowed to stop a prompt the gate already allowed. But **swallowing silently is the failure mode this whole subsystem exists to catch**: with a dead observer, `findings == []` means "we did not look", and that is indistinguishable from "nothing wrong".

`reconcile()` therefore returns the finding list *and its own trustworthiness*. Write failures are counted and logged at warning; an empty ledger, zero observations, or any failed write makes the result `UNTRUSTWORTHY (...) — absence of findings proves nothing`. Three tests pin the distinction.

This is the ADR-0116 §9 lesson applied reflexively: a measure that can fail quietly will eventually report a clean bill of health it did not earn.

## Consequences

- Prompt coverage gains a denominator that no naming trick evades and that spans languages — the 18 Markdown templates of #10858 are detectable without extending AST discovery.
- The reconciliation only speaks when it has data, so a dead observer is loud rather than reassuring.
- **Cost and limits, stated plainly:** matching is fuzzy, so this answers "does anything registered resemble this at all" and *not* "which builder exactly" — claiming that precision would be false. Findings require the factory to have run; there are no observations in CI, so this is a reconciliation against production data, not a build gate. And the ledger grows with traffic, bounded only by distinct shapes rather than volume, since repeats collapse on read.
- The AST ratchet stays. It fails fast in CI on the common case; this covers the case it cannot see. Neither subsumes the other.

## Precedent / Divergence

**Precedent:** ADR-0116 (prompts as a measured contract) for the registry, fitness scorecard and allowlist-with-reasons discipline; CH-6 `prompt_gate` (#9734) for the choke point and for the "counts and names, never content" audit rule this stream inherits.

**Divergence:** every coverage measure in this repo so far — loop fitness (ADR-0093), prompt fitness (ADR-0116), ADR enforcement (ADR-0100) — enumerates its denominator by walking the source. That is sound when the artifact class is syntactically identifiable, and prompts are not: they are defined by *where the text goes*, not by how the function is named or what language it is written in. Measuring at the destination instead of the source appears to be new here; no prior art was located for reconciling an LLM prompt-eval suite against observed production traffic. Recorded as honest novelty rather than assumed practice.
