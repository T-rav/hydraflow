# ADR-0143: PAAA — Purpose, Articles, Actors, Artifacts — and the declare / decide / act seam

**Status:** Accepted
**Date:** 2026-08-28
**Enforcement:** enforced
**Enforced by:**
- pytest:tests/test_charter.py::test_from_dict_loads_all_four_layers_plus_rails
- pytest:tests/architecture/test_policy_adr_enforcement_parity.py::test_engine_reproduces_the_ratchet_verdict_for_every_accepted_adr
**Binds:** factory
**Supersedes:** none
**Superseded by:** none
**Related:** [ADR-0044](0044-hydraflow-principles.md) (the audited principles — Articles made executable, and the register this ADR inventories), [ADR-0121](0121-rails-manifest-and-drift-caretaker.md) (the per-repo manifest and its drift caretaker — the surface that becomes the Articles declaration; renamed to `charter.yaml` by #11748), [ADR-0122](0122-vocabulary-scopes-for-the-three-assurance-disciplines.md) (the three assurance vocabularies — this ADR speaks the constitutional/legal one), [ADR-0132](0132-cognitive-process-constitution.md) (the cognitive-process constitution — the governance frame this ADR gives a concrete ontology to), [ADR-0136](0136-adr-drift-enforcement-deterministic-citation-gate.md) (drift enforcement as a deterministic gate rather than a loop — the same declare/decide/act split, already ruled for one Article class), [ADR-0138](0138-gateway-account-identity-and-sanitized-route-visibility.md) (the "No policy engine" non-goal this ADR scopes against, §"Scoping against ADR-0138" below), [ADR-0100](0100-adr-conformance-as-a-measured-contract.md) (conformance as a measured contract), [ADR-0123](0123-bidirectional-enforcement.md) (`**Binds:**` — the authority frame this ADR's ENACT/RATIFY guard extends), [ADR-0053](0053-ubiquitous-language-as-living-artifact.md) (the term files this ADR lands alongside it). Issues: #11747 (this ADR), #11752 (the epic), #11748 / #11749 / #11750 / #11751 (the siblings this ADR rules over), #11687 (prior use of the vocabulary), #11741 (the house standard fixing the Actors declaration).

**Precedent:** The chartered organization — a company is constituted by four declarations kept separately and read separately: a statement of objects (purpose), articles of association (the rules that must hold), a register of officers (who may bind the organization), and the statutory registers and minutes (the record). Second precedent: the policy-as-code separation formalized by XACML — an administration point where policy is *authored*, a decision point that *evaluates* it over attributes, and an enforcement point that *acts* on the verdict, with the decision point deliberately ignorant of how enforcement happens.
**Divergence:** in a chartered organization all four declarations are written by humans and read by humans, and the record is inert. Here three of the four are already machine-read and machine-checked while the fourth (Purpose) is read by nothing at all — so the model must state which layers are checkable rather than assume symmetry (receipt: the 2026-08-28 sweep recorded in #11752, which found the same governance shape re-derived five times with five exception formats and no named model). And unlike XACML, the decision point here is not authoritative: the pure-Python reference implementation is the specification and an external engine is a replaceable candidate behind a protocol (receipt: ADR-0138's standing "No policy engine" ruling, which this ADR scopes against rather than overturns), and no decision may depend on a service being reachable (receipt: #11687 — no conformance claim may rest on an external service being up).

> **Ratified 2026-08-29 by the operator (RATIFY), on the path this ADR reserved for it.**
> It names a model the repository already embodies five times over, and maps it onto surfaces
> that already exist. Its own first guard is that a system cannot enlarge its own mandate, so it
> did not enact itself: it landed Proposed and was accepted as a separate operator act.
> Accepted via §"On ratification" path 1 — **accept with real enforcement**, not by exemption,
> because the epic's children are the enforcement and an exemption claiming otherwise would
> have been false.

## Context

HydraFlow has independently evolved the same governance shape five times. Each time, the same six-step pipeline was re-derived from scratch, and each time it grew its own decision logic and its own exception format:

> `standard → evidence → classification → gate → exception/baseline → remediation`

| Re-derivation | Where the standard lives | Classification logic | Exception / baseline surface |
|---|---|---|---|
| ADR enforcement | `docs/standards/adr_enforcement/README.md` | `src/adr_conformance.py:classify_adr_enforcement` (REAL / WEAK / MISSING) | `docs/standards/adr_enforcement/exemptions.md` + `tests/architecture/adr_enforcement_baseline.json` |
| Disturbance ratchets | in-code, per finding signature | `src/disturbance/baseline.py:diff` (new / resolved / unchanged) | a YAML baseline written by `src/disturbance/baseline.py:save_baseline` |
| Erosion ratchets | in-code, one per erosion axis | a differently-named classifier per axis — `src/erosion/baseline.py:is_flagged` (change-spread), `src/erosion/scatter_baseline.py:diff`, `src/erosion/mass_baseline.py:grown`, `src/erosion/concentration_baseline.py:worsened`, `src/erosion/suite_hygiene_baseline.py:exceeded` | one baseline file per axis, and not even one directory: `disturbance/baselines/` for mass, concentration and suite hygiene; an uncommitted `erosion/baselines/` for spread and scatter |
| Charter drift | ADR-0121 | `src/charter.py:compute_charter_drift` (drift / undeclared-extra / unknown-layer / unknown-standard) | the charter's tolerance rules |
| AutoTighten | in-code, per setpoint series | `src/auto_tighten/engine.py:TighteningEngine` | monotone-violation guard |

Five implementations, five vocabularies, five exception formats, one idea. The erosion row is the whole finding in miniature: what is spoken of as one ratchet is five axes with five different verbs for *flagged*, and their baselines do not even share a directory. Nothing in the repository names the idea, so a sixth standard has no shape to conform to and will invent a sixth variant.

The vocabulary for that idea is already in use here, unnamed as a model. #11687 asks "do the articles hold, do artifacts stay true". ADR-0132 names the harness a governed cognitive-process manager and lists four constitutional mechanisms without naming the four *things* they govern. ADR-0122 already scoped the constitutional/legal register this ADR speaks in. What is missing is the decision of record that says what the model is and which surfaces already implement it.

A second gap sits underneath the first. Of the eight standards in `docs/standards/`, only three carry a machine-readable artifact next to the prose — `adr_enforcement/exemptions.md`, `branch_protection/gates.toml` (read by `src/gate_activation_check.py:check_gate_activation`), and `factory_autonomy/policy.yaml` (read by `src/merge_policy.py:MergePolicy`). The rest are prose a human must remember to apply. Closing that gap is #11751, and it needs this ADR's ontology to know what it is closing it *toward*.

## Decision

### Ruling 1 — The model is four layers, and only four

A HydraFlow-governed repository declares itself in four layers. Together they answer the four questions a system arriving cold must be able to answer from what the repository carries, without institutional memory:

| Layer | The question it answers | What it holds |
|---|---|---|
| **Purpose** | *What is this thing trying to do?* | Direction, goals, set-points, the intent the work serves |
| **Articles** | *What rules apply to it?* | What must remain true: standards, architectural constraints, security and compliance rules, local policy |
| **Actors** | *Who may change what?* | Who or what is authorized to act, and with what delegated authority |
| **Artifacts** | *What evidence and memory already exist?* | The software, plus ADRs, tests, evidence, manifests, ledgers, decisions |

The layers stay four. Evidence is not a fifth layer — it is Artifacts read as input. Feedback is not a fifth layer — the loops are what make the model *run*, not part of the model.

### Ruling 2 — The four layers map onto surfaces that already exist

This is the load-bearing table. It is an **inventory**, not a specification: with one exception noted in Ruling 3, every row names something already in the tree.

| Layer | Surfaces already carrying it | State today |
|---|---|---|
| **Purpose** | `README.md`; the description slot the onboarding kernel stamps into a new repository (`src/onboarding/kernel_writer.py:KernelSpec`); milestones and epic issues | **Implicit.** No declaration surface. See Ruling 3. |
| **Articles** | `docs/standards/` (eight standards; three with a machine-readable artifact — `adr_enforcement/exemptions.md`, `branch_protection/gates.toml`, `factory_autonomy/policy.yaml`); the ADR corpus, where an ADR carrying an *Enforced-by* block is a machine-checkable Article (`src/adr_conformance.py:classify_adr_enforcement`); `control/principles.yaml` (`src/principle_register.py:load_principles`); the per-repo charter of ADR-0121 as amended by #11748 (`src/charter.py:Charter`) | Real, scattered across five decision logics; a minority are checkable |
| **Actors** | The `agents/` tree — role contracts and chamber charters — which the 2026-08-25 house standard fixes as *the* Actors declaration (#11741); the role vocabulary a director may request (`src/driver_contracts.py:WorkerRole`); the per-repo data-governance class (`src/repo_store.py:RepoRecord`, enforced at every model spawn by `src/prompt_gate.py:most_restrictive_data_class`); the merge-policy autonomy classes — `act` / `ask` per `src/merge_policy.py:PolicyEntry`, declared in `docs/standards/factory_autonomy/policy.yaml` | Real; the directory *is* the declaration |
| **Artifacts** | `docs/arch/generated/` (regenerated every PR); the repo wiki `docs/wiki/`, including the term files of ADR-0053; the metrics streams under `.hydraflow/metrics/`; the append-only ledgers (`src/jsonl_ledger.py:AppendOnlyJsonlLedger`, `src/escape/ledger.py:EscapeLedger`); the kernel lock a stamped repository carries (`src/onboarding/kernel_lock.py:build_lock`) | Real, and by a wide margin the richest layer |

Read the table as a finding: **three of the four layers are already implemented and only unnamed.** The model is not new machinery. It is the name for machinery that exists.

### Ruling 3 — Purpose is implicit, and this ADR does not invent a surface for it

Purpose is the one layer with no declaration surface. Today it lives in `README.md` prose, in a one-line description the onboarding kernel stamps, and in milestone and epic text. Nothing reads any of them as a statement of intent, and nothing checks a decision against them.

This ADR **states that plainly and stops there.** Inventing a Purpose surface here would be designing, not recording, and would make the model's weakest layer its most speculative. Whether `charter.yaml` (#11748) carries a purpose block, and what if anything may be checked against it, is that issue's ruling to make against this ontology — not this ADR's.

### Ruling 4 — Enforcement of the Articles layer splits three ways

For the Articles layer specifically, enforcement separates into three parts with a strict division of labour:

```
declaration (YAML)         team-facing, reviewable in git, part of the Articles
        |
evidence collectors        tests, ratchets, ADR analysis, runtime probes
        |
normalized Facts
        |
decision layer             compliant | violated | exempt | grandfathered | blocking
        |
typed decision
        |
HydraFlow                  block, create work, remediate, verify, ratchet
```

- **YAML declares.** The declaration is the contract a team reads and reviews in a pull request. It is prose-adjacent, diffable, and owned by the repository.
- **A decision layer decides.** It consumes normalized facts and returns a verdict from a closed set — *compliant*, *violated*, *exempt*, *grandfathered*, *blocking* — plus the reason. It is pure over its inputs.
- **HydraFlow acts.** Blocking a merge, creating work, remediating, verifying, and ratcheting are HydraFlow's, and stay HydraFlow's.

The five re-derivations in the Context section each fuse all three parts into one function. Separating them is what makes a sixth standard cheap.

**OPA is a candidate for the decision layer, scoped to a bounded pilot — not a commitment.** The pilot (#11750) runs one standard whose semantics are already fully tested (ADR enforcement), parity-tested against the reference Python engine, and measured for expression size, latency, and composition cost. It carries a kill criterion decided in advance: if Rego exceeds 3× the Python it replaces and composition is not materially cheaper, it is not adopted and the finding is recorded. Teams never read Rego; the declaration is the contract and the engine sits behind a protocol with a pure-Python reference implementation as both the specification and the fallback. **An adopt verdict and a not-adopt verdict are equally successful outcomes of the pilot.**

### Ruling 5 — What the decision layer must never own

The decision layer is pure over normalized facts. It never:

- runs pytest, or any other test command;
- inspects git — history, diffs, branches, or working-tree state;
- launches agents or any model;
- creates, enters, or removes worktrees;
- repairs code, or writes to the repository at all;
- schedules anything, or owns a cadence;
- routes models or chooses a provider (that is the gateway's, per ADR-0139 through ADR-0142);
- manages pull requests;
- holds lifecycle state.

Every one of those stays in HydraFlow. The moment the decision layer does any of them it stops being replaceable, and the protocol it sits behind stops being a seam.

### Ruling 6 — The six guards

These constrain every sibling issue in the epic, and any later work that touches the model.

1. **PAAA is an ontology, not a file format.** The YAML manifest is HydraFlow's implementation surface and is never presented as "the PAAA spec". This epic produces no schema anyone outside HydraFlow is asked to conform to. Do not over-specify.
2. **Building standards are one class of Articles, not the whole of Articles.** Security rules, compliance obligations, architectural constraints, and local policy are Articles too. Do not collapse PAAA into standards, and do not collapse Articles into `docs/standards/`.
3. **Actors are declared by the `agents/` directory, never re-declared in YAML.** The manifest may *point at* the directory; it must not restate roles. Two declarations of who may act is one declaration too many, and the copy will rot.
4. **Changes to Purpose or Articles follow a different authority path from ordinary execution — ENACT, not RATIFY.** Ordinary execution is ratified against a standing mandate; changing the mandate is an enactment and is reserved to the operator. **The system cannot enlarge its own mandate.** Nothing in this epic automates an edit to the articles of a declaration.
5. **No conformance claim may depend on an external service being up** (#11687). Every decision must be reproducible offline from a clean checkout and recorded facts. A locally pinned binary is acceptable; a policy server is not, and neither is a network policy fetch.
6. **The four layers stay four.** Evidence and feedback do not become a fifth word. If something seems to need a fifth layer, it is Artifacts read as input, or it is a loop — and loops make the model run rather than belonging to it.

### Ruling 7 — Scoping against ADR-0138's "No policy engine"

ADR-0138 rules **"No policy engine"** as a non-goal of the gateway's observation phase, and that ruling stands. It is correct for routing, and nothing here weakens it: routing policy is resolved by the gateway's own purpose-built Python resolver (ADR-0139 through ADR-0142), in the request path, and this ADR does not propose changing that or re-litigating it.

The two concerns share the word "policy" and share nothing else. They differ on every axis that decides whether a general engine is warranted:

| Axis | Gateway routing (ADR-0138 → ADR-0142) | Standards conformance (this ADR) |
|---|---|---|
| Input shape | one mint request: repo, role, account and pool state, live capacity | a set of normalized facts collected from a checkout: test outcomes, ratchet diffs, ADR classifications |
| Where it runs | in the request path, per spawn | out of band, per pull request or on a cadence |
| Output | one binding chosen from a small enumerated set | a verdict per (article, subject) pair, composed across many articles |
| Audience | nobody outside HydraFlow reads it | teams read and review the declaration in git |
| Composition | none — one decision, one request | the whole point: articles that interact must compose |
| Reversal | must be reversible in flight (the canary of ADR-0141) | reversible by editing a declaration in a pull request |

**Both rulings hold simultaneously.** Routing policy stays in the gateway resolver, in Python, with no engine. The standards decision seam is a separate concern with a separate input shape, a separate latency budget, and a separate audience, and it is the only place an engine is even a candidate — behind a protocol, on a pilot, with a kill criterion.

## Non-goals — what this ADR deliberately does not decide

- **It does not specify a file format.** `charter.yaml`, its keys, and the fold of ADR-0121's rails fields under a `rails:` key are #11748's ruling. This ADR only rules that the declaration is the Articles surface.
- **It does not adopt OPA.** The pilot decides, against its kill criterion, in either direction.
- **It does not build cross-standard composition.** Composed standards are the reason an engine is interesting and are explicitly deferred; the pilot measures the cost, it does not pay it.
- **It does not migrate the five re-derivations.** They keep working exactly as they do. #11749 migrates one actuator as a proof; the rest is later work or never.
- **It does not create a standards framework or a marketplace.** Out of scope for the epic and out of scope here.
- **It does not promote the "building code" vocabulary.** That metaphor stays confined to the onboarding kernel where it was coined (`src/onboarding/kernel_writer.py:KernelSpec`, `src/onboarding/kernel_lock.py:build_lock`). Promoting it into the governance vocabulary would be a deliberate act, and this ADR declines to make it casually.

## Consequences

- **A sixth standard has a shape to conform to.** The next one declares, is decided over normalized facts, and is acted on by HydraFlow — instead of re-deriving classification, a baseline format, and a remediation path from scratch. That is the whole return on this ADR.
- **The naming ruling of 2026-08-28 is recorded.** The governing declaration is **`charter.yaml`**; ADR-0121's rails fields fold under a `rails:` key inside it. Rejected, with reasons: `build.yaml` (reads as CI), `standard.yaml` (singular, and reserved for the per-standard id file of #11751), `rails.yaml` (template vocabulary stretched past its meaning). ADR-0121's design is unchanged — only its file name and nesting move.
- **Purpose is named as the weak layer.** Making that visible is a result, not a defect of the ADR. It bounds how much any consumer may claim the repository declares about itself.
- **`PolicyDecision` is already taken.** `src/merge_policy.py:PolicyDecision` is the merge-policy verdict type and is a different, narrower object than the typed decision of Ruling 4. #11749 must either name its type differently or make the collision deliberate; it must not silently shadow the existing one.
- **The seam is testable before the engine exists.** Because Ruling 5 makes the decision layer pure, the reference Python implementation is the specification, and the pilot is a parity test rather than a migration.
- **Four terms enter the ubiquitous language.** `Purpose`, `Articles`, `Actors`, and `Artifacts` land in `docs/wiki/terms/` under ADR-0053, each anchored to a live symbol, so the four words stop being prose and start being checked They ship at `confidence: accepted` even though this ADR is Proposed: term files have no soft-launch lifecycle in this repo — the anchor-resolution and uniqueness gates are the admission test, and `tests/test_seed_terms.py::test_seed_terms_are_accepted` rejects any other value. If the framing is rejected, the four files are deleted rather than downgraded.
- **The Actors layer is cited by role, not by path.** The chamber directories beneath `agents/` are being renamed under #11741 while this ADR is written. The ADR names the tree and the role it plays; it deliberately does not hard-code a subdirectory path that is mid-rename.

## On ratification

This ADR is `decision-of-record` and carries no *Enforced-by* block, which is why it lands **Proposed**: an Accepted ADR with no real enforcement would either red the enforcement ratchet (`tests/architecture/test_adr_enforcement_ratchet.py::test_no_new_or_ungrandfathered_debt`) or need an exemption claiming no machine-checkable invariant is feasible — and that claim would be false, because the epic's own children are the enforcement.

On ratification, one of two paths applies:

1. **Accept with real enforcement**, once the sibling work lands — the manifest schema test (#11748), the prose-to-artifact bindings (#11751), and the decision-seam tests (#11749) are the checks an *Enforced-by* block would name.
2. **Accept with an exemption**, if the operator judges the ontology itself to be process-only, adding one justified line to `docs/standards/adr_enforcement/exemptions.md`.

Landing Proposed kept both open and enacted nothing — which is Guard 4 applied to this ADR itself.

**Outcome (2026-08-29): path 1.** The siblings landed — #11748 (`charter.yaml`, PR #11759), #11749
(the decision seam, PR #11757) — and their tests are named in the *Enforced-by* block above, so this
ADR classifies `REAL` rather than adding unenforced-decision debt. Path 2 was not taken: the
ontology is not process-only, and an exemption asserting no machine-checkable invariant was
feasible would have been false on its face.

One nominated check is **not yet cited**: the prose-to-artifact bindings (#11751, PR #11758) were
still open at ratification. `REAL` requires only that at least one typed check resolves, and two do,
so the block is honest as it stands rather than citing a test that does not yet exist — which would
have classified `WEAK` and created the very debt this section exists to avoid. Add
`pytest:tests/architecture/test_standards_registry.py::TestReadmeAndYamlAreOneSet` when #11758 lands.
