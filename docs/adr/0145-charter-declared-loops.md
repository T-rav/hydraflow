# ADR-0145: Charter-declared loops — the repo owns the workflow, the factory owns governance

**Status:** Proposed
**Date:** 2026-08-31
**Enforcement:** enforced
**Enforced by:**
- pytest:tests/test_charter_loops_schema.py::TestBidirectionalBinding::test_an_actor_that_moved_to_a_package_is_still_enumerated
- pytest:tests/test_charter_loops_schema.py::TestBidirectionalBinding::test_an_actor_named_by_no_loop_is_a_drift_finding
- pytest:tests/test_charter_loops_schema.py::TestMisparseIsLoud::test_a_loop_body_that_is_not_a_mapping_raises
- pytest:tests/test_charter_loops_schema.py::TestEmptyIsNotAbsent::test_the_two_are_distinguishable_on_a_loaded_charter
- pytest:tests/test_charter_loops_schema.py::TestDuplicateKeysAreAnError::test_the_guard_covers_the_whole_charter_not_only_loops
- pytest:tests/test_charter_loops_schema.py::TestTriggerVocabularyIsBound::test_an_on_clause_is_rejected_citing_this_adr
**Binds:** factory
**Supersedes:** none
**Superseded by:** none

**Precedent:** GitHub Actions and GitLab CI, where the repository declares which
workflows exist and when they run while the platform owns isolation, secrets,
retries and the merge gate (`.github/workflows/*.yml`; GNAA's `loops.yml`, the
evidence repo for this design)
**Divergence:** a CI workflow declares *steps* — an ordered list of commands the platform executes literally. A charter loop declares an *actor and a goal*, and the executed behaviour comes from a markdown contract the platform renders as a system prompt, so the platform cannot validate the work by reading the declaration. Every binding here is therefore checked structurally rather than trusted: an unresolvable actor, an unbound trigger, or a duplicate key is an error at load, not a run that quietly does nothing. (receipts: #11669 — the ten-instance path-membership class this ADR's enumeration predicate is written against; #11751 — the one-way binding that let `standard.yaml` and its README drift; GNAA hit the duplicate-key defect and fixed it in `bin/lib/loops.py:load_loops`, and its own `loops.yml` header concedes "today the Operator is the event detector for all of them")

## Context

`charter.yaml` `schema_version: 1` declares **what a repo is** — its purpose,
articles, actors and artifacts ([ADR-0143](0143-paaa-governance-model-and-the-decision-seam.md)).
It cannot declare **what runs**. Every agent HydraFlow executes is a catalogued
Python class: `DirectorTurnRunner`, `PlanWorkerRunner`, `ReviewWorkerRunner`.
Adding an agent to a repo means adding a class to the factory.

`docs/proposals/charter-declared-loops-v1-1-0.md` (revised 2026-08-29 against
its own evidence repo) proposes the inversion: the repo declares which actors it
has and when they run; HydraFlow runs the outer loop. The proposal is reviewed
and on `main`, but a proposal is not a decision, and its three open operator
questions were answered in a session on 2026-08-31 — that is, nowhere durable.
The v1.1.0 implementation children (#11860, #11861, #11862, #11863) have no
ruling to conform to until this exists.

**The evidence is one repo, and it is not an independent sample.** GNAA is the
only repository running this pattern, and it was built by the same operator. The
proposal says so plainly, and this ADR inherits that limitation: what follows is
ruled from one worked example plus this repo's own defect history, not from a
population.

## Decision

### 1. The contract: `schema_version: 2`, a `loops:` block keyed by loop

```yaml
schema_version: 2

actors: agents/          # UNCHANGED — still a pointer, never a roster

loops:
  records-docket:
    actor: records       # defaults to the key when omitted
    enabled: true
    trigger:             # a LIST of clauses; any may fire the loop
      - cron: "0 9 * * MON"
    goal: >
      Produce the docket: every open request with its custodian, statutory due
      date, state, and next action.
    budget_usd: 4.00
    timeout_s: 900
    model: sonnet
    output:
      branch_prefix: "records/"
      gate: pr
```

**Keyed by loop, `actor:` defaulting to the key.** The loop↔actor relation is
many-to-one: GNAA runs `records` and `records-quarterly` over one
`agents/records.md`. Its runtime already resolves this by trimming a name suffix
(`bin/convene`: *"tried trimming to a base agent"*). Making the relation
explicit beats inferring it from a naming convention, because a convention is a
predicate over names, and predicates over names are what this repo keeps getting
wrong (#11669, #11723, #11781).

**`enabled: false` IS dormancy.** No separate `dormant:` list. A second list is a
second roster in miniature — the exact shape `_parse_actors` already exists to
reject — and it admits both contradiction (an actor in both lists) and staleness
(a dormant entry naming a deleted actor). One table, one namespace, no
both-lists state.

**The envelope ships at v1.1.0.** `budget_usd`, `timeout_s` and `model` are in
the schema from the start, not bolted on. A kernel worker needs all three on day
one; the only question was whether they are schematised or improvised, and GNAA
already has them plus a budget-refusal exit path.

**`gate: pr` is the only value at v1.1.0.** It names what already happens rather
than inventing policy.

### 2. The five guards, each anchored to a shipped defect

Each is non-negotiable and ships with its own test.

**Guard 1 — bidirectional resolution, with a DEFINED enumeration predicate.**
Every loop's `actor` resolves to an actor file, *and* every actor file is named
by at least one loop. One-way binding is how `standard.yaml` and its README
drifted until #11751.

The enumeration predicate is part of the contract, not an implementation detail:
top-level `agents/*.md` **plus** `agents/<name>/README.md`, minus `README.md`
and `runtime.md`, minus governance directories (`council/`, `board/`,
`operator/`). A narrower predicate — "top-level `*.md` minus README" — silently
stops seeing an actor the day it moves from `finance.md` to `finance/README.md`.
That is this repo's documented ten-instance path-membership class (#11669),
where a membership test matching nothing returns `False` and nothing reddens.

It therefore ships with a **mutation test** performing exactly that
module→package move and asserting the guard still sees the actor. A missing side
of the binding is a **drift finding, not a load error**: a repo mid-migration
must still load.

**Guard 2 — a mis-parse fails LOUD, never "dormant."** An unparseable `loops:`
block raises `CharterError`. `src/charter.py` already draws this line correctly
one level up: `load_charter` returns `None` only for a repo with *no* charter.

**Guard 3 — empty is not absent.** A present-but-empty `loops: {}` declares that
nothing runs, and is valid. A missing block means an unmigrated repo. The
caretaker skips the second and must not skip the first.

This extends `charter.py`'s fail-loud convention and explicitly **not**
`policy.models.Charter.governs()`'s fail-open one. The two words live in one
codebase and mean opposite things; naming which one applies is the point.

**Guard 4 — duplicate keys are an error.** `yaml.safe_load` silently keeps the
last duplicate. Two `finance-close:` entries — one `enabled: true`, one `false` —
load clean, schema-validate clean, and the first vanishes. GNAA already hit this
and already fixed it (`bin/lib/loops.py:load_loops`). The loader uses a
duplicate-key-rejecting constructor, applied **charter-wide**: today's
`_read_mapping` has the same hole for the charter as a whole and is fixed in the
same change.

**Guard 5 — trigger vocabulary is bound, like actors are.** `on: <event>` values
resolve against a declared event registry; an unresolvable one is a
`CharterError`. Without this, `on: inbound_recieved` is schema-valid and the loop
silently never fires — silence-as-failure one field over.

**Also settled:** if both `agents/x.md` and `agents/x/README.md` exist, that is a
`CharterError`. Two files for one key is the two-tables defect at file
granularity.

### 3. Operator rulings (2026-08-31)

**Ruling 1 — a per-run `goal` override is ALLOWED**, and every override is
recorded in the run receipt. Unrecorded input is disqualifying; recorded input
is fine. The receipt is what makes the difference, not the override.

**Ruling 2 — an enabled loop with an unparseable actor contract REFUSES the run
and alerts.** It files nothing and never degrades to a default prompt. A default
prompt would produce plausible work attributed to an actor whose contract nobody
could read — worse than no run, because it looks like a run.

**Ruling 3 — `on:` event triggers are DEFERRED. v1.1.0 ships `cron` clauses
only.** The schema reserves the `on:` shape; the validator rejects it with a
message naming this ADR. Chosen because `on:` is aspirational even in the
evidence repo, whose own `loops.yml` header says *"today the Operator is the
event detector for all of them."* Shipping a field that looks automatic but
requires a human detector is silence-as-failure one field over — guard 5's own
objection, applied to guard 5's own feature. `on:` returns when a detector
exists.

### 4. What each side owns

| | owns |
|---|---|
| **the repo** | which actors exist · what each is for · when it runs · what done looks like |
| **the factory** | worktree isolation · PR lifecycle · label/phase transitions · review gates · HITL escalation · credit exhaustion · watchdogs · workspace GC |

The repo half is markdown plus one YAML block. The factory half is machinery
HydraFlow already has and a repo should never reimplement. That asymmetry is the
whole argument for the inversion: the parts a repo would get wrong are exactly
the parts it no longer writes.

### 5. The kernel worker

One generic runner parameterised by charter rather than by code. Per tick:

1. Load the target repo's `charter.yaml`; refuse loudly if `loops` is unparseable.
2. Select due loops (`enabled`, and any `trigger` clause fired).
3. For each: create an isolated worktree, render the actor's charter file as the
   system prompt with `goal` as the task, dispatch one brokered worker inside its
   envelope.
4. Hand the output to the existing gates — branch, PR, labels, review, merge policy.
5. Record a receipt.

Steps 1–3 are new. Steps 4–5 already exist, and that is the reason this is worth
doing at all.

**The kernel may never enable a loop.** Enabling is an ENACT belonging to a
human, already ruled by [ADR-0143](0143-paaa-governance-model-and-the-decision-seam.md)
Ruling 6 guard 4. This ADR adds no new authority; it adds a declaration surface
under the authority that already exists.

## Consequences

**Migration is additive.** `schema_version: 1` charters keep loading unchanged.
An absent `loops` block means "no charter-declared loops", which is every repo
today.

**A new failure mode: a repo can declare a loop the factory then refuses to
run.** Guards 1, 2, 4 and 5 all turn a malformed declaration into a load error,
which surfaces as a broken charter rather than a quiet non-run. That is the
intended trade — the alternative is the pattern this whole ADR exists to avoid.

**The one-sample limitation stays live.** Every ruling above is derived from one
repo built by the same operator, plus this repo's defect history. A second
independent adopter is the evidence that would confirm or break these choices,
and none exists yet. Rulings that turn out to be GNAA-shaped rather than
generally right should be superseded on that evidence, not defended.

**Enforcement landed with #11860.** This shipped as `decision-of-record`
because the five guards named tests that did not exist yet, and listing them as
`Enforced by:` anchors would have been six citations resolving to nothing — the
dangling-anchor class this repo has already paid for twice (#11781, and the
term-file anchors that resolved green while their prose cited a deleted class).
#11860 added the tests and flipped the status in the same change, which is the
only sequence that never leaves a decision nothing checks.

**`on:` is a reserved hole.** The schema carries a shape the validator rejects.
That is deliberate — it keeps migration lossless for repos whose prose triggers
say "and on each telemetry candidate" — but a reserved field that always errors
is itself a small lie, and it should not survive more than one minor version
without either a detector or removal.
