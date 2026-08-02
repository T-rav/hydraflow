# ADR-0122: Vocabulary scopes for the three assurance disciplines

**Status:** Proposed
**Date:** 2026-08-01
**Enforcement:** decision-of-record
**Related:** [ADR-0053](0053-ubiquitous-language-as-living-artifact.md) (UL as a living artifact — the term store this ADR scopes), [ADR-0054](0054-term-auto-proposer-loop.md) (term-proposal machinery), [ADR-0099](0099-orchestration-as-a-control-system.md) (orchestration as a control system — the canonical control roles), [ADR-0100](0100-adr-conformance-as-a-measured-contract.md) (conformance ratchet), [ADR-0101](0101-disturbance-dampener.md) (the reference regulator), [ADR-0120](0120-stillness-control-architecture.md) (setpoint regulators)
**Addresses:** #10834 (this scoping ADR). Sequenced **before** #10831 (ADR-corpus coherence dig) so register collisions are not reported as contradictions. Register neighbours: #10833 (formal methods — the kernel proof), #10819–#10832 / #10829 (the control/stillness program).

**Precedent:** Bounded Context + Ubiquitous Language (Eric Evans, *Domain-Driven Design*, 2003) — vocabulary is scoped to a context, and the same word legitimately carries different meanings in different contexts, resolved by naming the context rather than renaming the word.
**Divergence:** DDD assumes contexts map to separated subsystems/teams, each with its own model boundary, so a collision term never co-occurs unqualified inside one artifact; here the three assurance disciplines (constitutional/legal, formal methods, control theory) share **one** codebase and **one** ADR corpus, so the collision terms co-occur in a single document with no subsystem boundary to keep them apart — forcing an explicit per-term *register* convention (default owner + qualified forms) rather than a context-per-subsystem split (receipt: #10834; forcing condition: the #10831 coherence dig would otherwise surface these register collisions as apparent contradictions and spend its first pass on false positives).

> **This is a Proposed ADR — a design ruling for decision, not an accepted commitment.** The *approach* below (three scopes + a per-term register convention) is what the owner signed on #10834 (2026-07-29, "approved, proceed"). The *specific resolutions* of the seven collision terms are drafted set-point text: the factory drafts, the author signs the wording. Accept, amend, or reject the individual defaults.

## Context

The factory has acquired three assurance disciplines with overlapping words:

- **Constitutional/legal design** governs *authority* — who may change what, by what procedure, reviewed by whom, and why anyone outside should accept it: the ADR corpus, gate immutability, allowlists, escalation, human-signed envelopes.
- **Formal methods** govern the *kernel's correctness* (#10833): does the gate/verdict logic do what the rules say, under every interleaving.
- **Control theory** governs *dynamics* (#10819–#10832, #10829): will it hold, can it rest, is it drifting.

The three compose cleanly — the rules say it, the proof checks the kernel obeys it, the instruments watch what neither can reach — but they share vocabulary. Seven words already carry a different meaning in each register (`verdict`, `setpoint`, `invariant`, `authority`, `gate`, `independence`, `erosion`). Left unscoped, three registers in one ADR corpus muddle: a reader cannot tell whether "invariant" means *proven*, *monitored*, or *asserted*, and the #10831 coherence dig will read a register collision as a contradiction.

The CI-enforced UL store already exists ([ADR-0053](0053-ubiquitous-language-as-living-artifact.md) term files + [ADR-0054](0054-term-auto-proposer-loop.md) proposal machinery, plus [ADR-0099](0099-orchestration-as-a-control-system.md)'s canonical control roles), so this is a **scoping addition, not new infrastructure**. Doing it now is the cheap version: retrofitting disambiguation across ~90 ADRs after the corpus mixes is the expensive one.

## Decision

### 1. Assign each discipline a vocabulary scope (register)

Every UL term belongs to a **register** — the discipline whose meaning it carries by default:

| Register | Discipline | Governs | Canonical anchors |
|----------|-----------|---------|-------------------|
| **legal** | Constitutional/legal design | authority, procedure, entrenchment | the ADR corpus, allowlists, `models.py:HitlEscalation` |
| **formal** | Formal methods | proven correctness of the kernel (#10833) | the kernel proof, model-checker verdicts |
| **control** | Control theory | dynamics: stability, rest, drift | `signal_control/controllers.py:PidController`, `erosion_metrics_loop.py:ErosionMetricsLoop` |

The register is recorded **in each term's Definition prose** (the UL `Term` schema has no scope field today, so scope lives in the body — see *Consequences*). A term whose word is unambiguous keeps its single meaning; a **collision term** names its default owner and the qualified forms the other registers must use.

### 2. The register convention for collision terms

For each collision term: **one register owns the bare word**; the other registers must **qualify** (e.g. "monitored invariant", "model-family independence"). This is exactly DDD's "name the context" move, applied per-term because the contexts share one corpus.

### 3. The seven collision resolutions (drafted — author signs the wording)

Each is a new UL term file under `docs/wiki/terms/`. The **default owner** is the drafter's proposal; every one is an adjustable set-point.

| Term | Default owner (bare word) | Qualified forms in other registers |
|------|---------------------------|------------------------------------|
| **verdict** | **control/kernel** — a gate's pass/fail (`convergence_gate.py:JudgeVerdict`) | *model-checker verdict* / counterexample (formal, #10833); *adjudication* (legal ruling) |
| **setpoint** | **control** — a regulator's reference signal (`signal_control/controllers.py:PidController`) | a *specification* (written requirement); a *ruling* (ADR decision) — neither is a "setpoint" |
| **invariant** | *(none — always qualify)* | *proven* (formal), *monitored* (control), *asserted* (legal); bare "invariant" overclaims |
| **authority** | **legal** — jurisdiction, who holds the decision (`models.py:HitlEscalation`) | *actuation authority* (control: what a loop may do, bounded by the Governor) |
| **gate** | **control/kernel** — the mechanism (`convergence_gate.py:Gate`) | *gate policy* / entrenched gate rule (legal: gate immutability, the allowlist) |
| **independence** | **evidence/formal** — model-family diversity (`judge_independence.py:IndependenceDisposition`, #10371/#10832) | *institutional independence* (legal: a structurally separate reviewer) |
| **erosion** | **control, plant-side** — code decay (`erosion_metrics_loop.py:ErosionMetricsLoop`) | *setpoint erosion* (control, reference-side, #10829): the target drifting, not the plant |

Note two terms deliberately break the "one owner" default:

- **invariant** has *no* default owner — the word must always be qualified, because the bare form silently claims *proven* and none of the three registers should be allowed to annex it.
- **erosion** is owned within **one** register (control) but split across its two *sides* (plant vs reference) because #10829 (setpoint erosion) and plant-side code decay have **opposite remedies** (tighten the plant vs restore the setpoint) and must not share a bare word.

### 4. Partition / jurisdiction split (same ADR)

Partition boundaries are **jurisdictional** (legal scope: which authority owns a region), while their **sizing** is **measured** (control scope, via context-cost). Naming that split now keeps the decomposition work (#10819-program) from straddling registers: "where the boundary *is*" is a legal decision; "how big it *should be*" is a control signal.

## Consequences

- **Positive.** The #10831 coherence dig can treat a register-qualified word as intentional, not contradictory — its first pass is signal, not false positives. New ADRs inherit a convention instead of improvising per-author. The seven terms are now CI-anchored (ADR-0053 lint): each resolves to a live class, so the register scoping cannot silently drift from code.
- **Schema gap (flagged for the author).** The `Term` model (`ubiquitous_language.py:Term`) has **no `register`/`scope` field today; #10831's note anticipated one.** This ADR records register in Definition prose as an interim. If the author wants register machine-queryable (e.g. to lint "unqualified collision word used outside its owning register"), that is a follow-up schema addition (new optional field + renderer column + a lint rule) — deliberately **not** bundled here to keep this a pure scoping decision.
- **`code_anchor` is a representative, not a claim of sole ownership.** Each collision term anchors to the one class that best embodies its default register (a UL term carries exactly one anchor); the other registers' embodiments are named in the term's prose, not as anchors.
- **Confidence.** The seven term files ship at `confidence: accepted` — the codebase invariant (`tests/test_seed_terms.py::test_seed_terms_are_accepted`, ADR-0054) is that *all* committed terms are `accepted`; there is no soft-launch term lifecycle. The "not yet signed" state of the specific wording is carried by **this ADR's `Proposed` status**, not by the term confidence. When the author amends a resolution, the term file's Definition changes with it.

## Alternatives considered

- **One term per (word × register)** — e.g. `verdict-control`, `verdict-formal`, `verdict-legal`. Rejected: it triples the glossary, breaks the one-word/one-file intuition, and still needs a convention for which spelling is the bare default. The register-convention approach keeps one term per word and encodes the split in prose.
- **A `bounded_context` per discipline** (add `legal` / `formal` / `control` to the `BoundedContext` enum). Rejected here: bounded context in this codebase already means an architectural boundary (`caretaker` / `builder` / `shared-kernel`), and these disciplines cut *across* those boundaries. Overloading `bounded_context` would itself be a register collision. A dedicated `register` field (see *Consequences*) is the honest shape if machine-queryable scope is wanted.
- **Defer until #10831 surfaces the collisions.** Rejected on the issue's own sequencing argument: deferring guarantees the coherence dig's first output is mostly false positives, and the retrofit cost grows with every ADR added in the meantime.
