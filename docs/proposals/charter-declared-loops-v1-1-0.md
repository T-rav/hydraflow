# Charter-declared loops — the repo owns the workflow, the factory owns governance

**Status:** Proposal · targets v1.1.0 · `charter.yaml` `schema_version: 2`
**Date:** 2026-08-29 · **Revised:** 2026-08-29 (v1.1.1, post-review)
**Relates:** ADR-0143 (PAAA), ADR-0121 (the manifest), ADR-0042 (two-tier promotion), #11748 (charter.yaml), #11035 (cognitive-process manager)

## Revision note — what the review changed

The first draft of this document was reviewed against its own evidence repo and
**three of its claims did not survive contact with that repo's actual config.** The
`loops:` contract below is the amended one; the original's defects are recorded inline
where they were found, because each is an instance of a class this repo keeps hitting.

| | first draft | why it was wrong |
|---|---|---|
| loop↔actor | one-to-one, key resolves to the actor file | GNAA runs **15 loops over 11 charters**. The relation is many-to-one in 4 of 15 entries. The schema rejected its own evidence. |
| `trigger` | `cron` xor `on` | GNAA's real triggers are conjunctions (`weekly · and on each telemetry candidate`). A third of its loops are both scheduled *and* event-woken. |
| loader | "must be a real YAML load" | `yaml.safe_load` keeps the **last** duplicate key silently. GNAA already hit this and already guards it; the prescription would have reintroduced the defect. |
| `hydration:` | a new declaration block | **Withdrawn.** Its premise was false — see [Re-hydration](#re-hydration-the-boundary-that-already-exists). |

The trigger defect is the one worth naming: the first draft committed **a predicate
narrower than the vocabulary of the thing it described**, inside the section citing the
fifteen narrow-predicate guards found on 2026-08-29. The class does not spare the
document that describes it.

## The idea in one line

A repo declares **what agents it has and when they should run**; HydraFlow runs the
**outer loop** — isolation, PR lifecycle, gates, escalation — for every repo without
reimplementing any of it per repo.

## The evidence: one repo, and it is not an independent sample

`T-rav/goodneighboraviation.org` runs this pattern today:

```
agents/<name>.md              the charter IS the agent — role definition and prompt in one file
agents/{board,council,operator}/
agents/loops.yml              enabled · trigger · goal — the repo's own loop registry
bin/convene <agent> [goal]    ONE generic runner. No per-loop code.
bin/lib/{loops,budget,dispatch,lock,health,log_run}.py
output = branch + PR          bin/convene's own header: "the merge is the gate"
.github/workflows/convene.yml the outer loop, such as it is
```

Eleven markdown charters and one YAML file, with no Python per loop. Its governance is
"open a PR and let a human merge it" — which is correct, and is also exactly the half
HydraFlow already has industrialised.

**But the sample is n=1 and it is not independent.** GNAA has the same operator and the
same governance vocabulary as HydraFlow — activation ladders, council decisions,
ENACT/RATIFY framing, "the charter is the agent." That it works there is evidence that
**the author's pattern ports**, not that the pattern is general. The generality claim
needs a second repo that did not come from this desk.

**The two halves are shaped to fit.** `charter.yaml` declares `actors: agents/`. GNAA
*has* `agents/`. Neither was built for the other — that part is real.

### What the pattern silently requires

Every actor's work-product must be **a file whose diff is the deliverable**. GNAA is an
organisation that lives inside a repo: reports, dockets, drafts and minutes are files,
and its agents deliberately stage rather than act — correspondence triages but never
sends, outreach "stages gated touches." `gate: pr` is coherent there precisely because
nothing has effects outside the tree.

It does **not** fit a repo whose loops act on the world — deploy, restart, page, actually
send the email. There, "the merge is the gate" gates nothing: by the time a diff exists
the action already happened, or the diff is an empty ritual. Nor does it fit genuinely
external triggers; HydraFlow's event vocabulary is GitHub-shaped, and even GNAA's
`on:` triggers are today a human noticing something. That limit belongs in the contract,
not in a footnote.

## The constraint that shapes the design

`src/charter.py:27`:

```
actors: agents/                           # pointer ONLY, never a role list
```

This is enforced — `_parse_actors` raises `CharterError` on a role list, per ADR-0143
Ruling 6. The reason is not stylistic: a roster in the charter plus a directory of actor
files is **two tables over one vocabulary**, the same defect that shipped as the dual
`Charter` classes (`src/charter.py:416` and `src/policy/models.py:133`).

Note that those two classes **already disagree about empty** on the one field they
share: `policy.models.Charter.governs()` is deliberately fail-OPEN on an empty
`standards` list ("no charter has been written yet"), while `charter.py` treats an empty
charter as fatal `uncheckable-charter`. Guard 3 below therefore enters contested
vocabulary and must say which convention it extends. It extends `charter.py`'s.

So `loops.yml` **cannot** simply move into `charter.yaml` as a roster. The contract must
declare *behaviour*, with the actors themselves still derived from the directory.

## The contract

`charter.yaml`, `schema_version: 2`:

```yaml
schema_version: 2

actors: agents/                    # UNCHANGED. Still a pointer, never a roster.

loops:                             # NEW. Keyed by LOOP, not by actor.
  finance-close:
    actor: finance                 # defaults to the key when omitted
    enabled: true
    trigger:                       # a LIST of clauses — any may fire the loop
      - cron: "0 9 1 * *"
    goal: >
      Produce the monthly close per your output contract from the ledger in
      this repo.
    budget_usd: 4.00               # the envelope GNAA proved necessary
    timeout_s: 900
    model: sonnet
    output:
      branch_prefix: "finance/"
      gate: pr                     # the merge is the gate

  records-docket:
    actor: records
    enabled: true
    trigger:                       # scheduled AND event-woken — the D2 case
      - cron: "0 9 * * MON"
      - on: records_request_response_received
    goal: >
      Produce the docket: every open request with its custodian, statutory due
      date, state, and next action; flag any clock inside three working days.

  records-quarterly:               # a SECOND loop over the same actor
    actor: records
    enabled: true
    trigger:
      - cron: "0 9 1 */3 *"
    goal: >
      Stage ONE records request per airport, rotating through the set.

  pr-moment:
    actor: pr
    enabled: false                 # dormancy is a value, not a second list
    trigger:
      - on: press_moment
    goal: As dispatched.
```

### Field notes

- **Keyed by loop, `actor:` defaults to the key.** This is the D1 fix. GNAA runs
  `records` and `records-quarterly` over one `agents/records.md`; the first draft's
  schema could not express that, and GNAA's own runtime already resolves it by
  suffix-trimming (`bin/convene`: *"tried trimming to a base agent"*). Making the
  relation explicit beats inferring it from a naming convention — a convention is a
  predicate, and predicates over names are what this repo keeps getting wrong.
- **`trigger` is a list of clauses, each `cron` xor `on`.** This is the D2 fix. A loop
  fires when **any** clause fires. GNAA's prose triggers (`weekly · and on each
  telemetry candidate`) are readable and unschedulable; the schema must be able to hold
  what the prose says, or migration is lossy by construction.
- **`goal` is the run's task inside the charter, not a replacement for it.** GNAA's
  framing — "the charter is the agent; the goal is the run's task inside it" — is the
  right one and survives the move.
- **The envelope (`budget_usd`, `timeout_s`, `model`) is in v1.1.0, not bolted on
  later.** GNAA already has all three plus defaults and a budget-refusal exit path
  (`bin/lib/loops.py`, `bin/lib/budget.py`). A kernel worker needs them on day one; the
  only question is whether they are schematised or improvised.
- **`enabled: false` IS dormancy.** The first draft's separate `dormant:` list was a
  second roster in miniature — the exact shape `_parse_actors` exists to reject. It also
  admitted contradiction (an actor in both lists) and staleness (a dormant entry naming
  a deleted actor). One table, one namespace, no both-lists state.
- **`gate: pr`** is the only value at v1.1.0. It names what already happens rather than
  inventing policy.

## Five guards, each earned by a real failure

**1. Bidirectional resolution.** Every loop's `actor` resolves to an actor file, *and*
every actor file is named by at least one loop. One-way binding is how `standard.yaml`
and its README drifted until #11751 bound them.

This requires a thing the first draft left undefined: **a predicate for "every actor
file."** GNAA's `agents/` holds `README.md` and `runtime.md` (a stage-plan document, not
an actor) beside eleven real charters, plus chamber directories; HydraFlow's holds
`council/decisions/` records and `.gitkeep`s. Any narrow enumeration — "top-level `*.md`
minus README" — **silently stops seeing an actor the day it moves from `finance.md` to
`finance/README.md`**. That is this repo's documented ten-instance path-membership
class (#11669), where a membership test that matches nothing simply returns `False` and
nothing reddens. The enumeration predicate is part of the contract, and it ships with a
mutation test that performs exactly that module→package move and asserts the guard
reddens.

**2. A mis-parse must fail LOUD, never "dormant."** An unparseable loops block is an
error, never an absence. `src/charter.py` already draws this distinction correctly for
the charter as a whole — `load_charter` returns `None` only for a repo with *no* charter
— and the same rule holds one level down.

**3. Empty is not absent.** A present-but-empty `loops:` block declares that nothing
runs. A missing block means an unmigrated repo. The caretaker skips the second and must
not skip the first. Per the contested-vocabulary note above, this extends `charter.py`'s
fail-loud convention, **not** `policy.models.Charter.governs()`'s fail-open one.

**4. Duplicate keys are an error.** `yaml.safe_load` silently keeps the last duplicate.
Two `finance-close:` entries — one `enabled: true`, one `false` — load clean,
schema-validate clean, and the first vanishes. This is not hypothetical: GNAA **already
hit it and already fixed it** —

```python
# bin/lib/loops.py:65-68
# A duplicate key silently overwrote the first declaration, so a loop could
raise ValueError(f"duplicate loop {agent!r} in loops.yml")
```

The first draft's prescription — "the loader must be a real YAML load" — would have
**reintroduced the defect the hand-written parser it disparaged was guarding against.**
The loader uses a duplicate-key-rejecting constructor. This also afflicts today's
`_read_mapping` for the charter as a whole, and should be fixed there in the same change.

**5. Trigger vocabulary is bound, like actors are.** Guard 1 binds actors
bidirectionally; nothing in the first draft bound `on: <event>` values to anything.
`on: inbound_recieved` is schema-valid, and the loop silently never fires — silence-as-
failure one field over. `on:` values resolve against a declared event registry, and an
unresolvable one is a `CharterError`.

This forces an honest admission the first draft skipped: **`on:` is aspirational even in
the evidence repo.** GNAA's own `loops.yml` header says "today the Operator is the event
detector for all of them." Shipping `on:` means either shipping the detector or shipping
a documented manual trigger — not shipping a field that looks automatic.

**Also settled:** if both `agents/x.md` and `agents/x/README.md` exist, that is a
`CharterError`. Two files for one key is the two-tables defect at file granularity.

## What each side owns

| | owns |
|---|---|
| **the repo** | which actors exist · what each is for · when it runs · what done looks like |
| **the factory** | worktree isolation · PR lifecycle · label/phase transitions · review gates · HITL escalation · credit exhaustion · watchdogs · workspace GC |

The repo half is markdown plus one YAML block. The factory half is the machinery
HydraFlow already has and a repo should never reimplement.

## The kernel worker

`bin/convene`, moved outward: **one generic runner parameterised by charter rather than
by code.** HydraFlow already has the runner shape — `DirectorTurnRunner`,
`PlanWorkerRunner`, `ReviewWorkerRunner` — what it lacks is one that takes its role from
*the repo's* declaration instead of a catalogued Python class.

Sketch of the tick:

1. Load the target repo's `charter.yaml`; refuse loudly if `loops` is unparseable.
2. Select due loops (`enabled` and any `trigger` clause fired).
3. For each: create an isolated worktree, render the actor's charter file as the system
   prompt with `goal` as the task, dispatch one brokered worker inside its envelope.
4. Hand the output to the existing gates — branch, PR, labels, review, merge policy.
5. Record a receipt.

Steps 1–3 are new. Steps 4–5 already exist and are the reason this is worth doing.

## Re-hydration: the boundary that already exists

**The first draft proposed a `hydration:` block. It is withdrawn.** The premise it rested
on was false, and an audit of the actual mechanism — which the first draft deferred as
"part of the work" — showed the boundary it wanted to build is already there.

**No comment marker is load-bearing, because no marker is read.** The markers exist at
exactly five sites, all inside `_claude_md`:

```
src/onboarding/kernel_writer.py:281,282,299,301,302   the only definitions
tests/test_onboarding_kernel_writer.py:136-138        the only reference: "is the string present"
```

No parser, no matcher, no honour-check anywhere in the repo. The real enforcement is the
`Ownership` enum in `stamp_kernel`: CLAUDE.md is `Ownership.PRODUCT`
(`kernel_writer.py:570`) and is **never rewritten, even under `--force`**
(`kernel_writer.py:710-714`). Two consequences, both inverting the first draft:

1. Its premise — "the markers stop being an enforcement mechanism" — mis-states the
   present. **They never were one.** No stamped region is protected only by a marker, so
   no `hydration.owned` entry is needed to complete any migration. The feared "moved the
   problem instead of fixing it" outcome is empty.
2. `hydration.managed` duplicates a table that already exists.
   `hydraflow-kernel.lock` (`src/onboarding/kernel_lock.py`) is the committed, per-file,
   hash-anchored record of what the kernel prescribed, with a four-state freshness
   classifier — `CURRENT / KERNEL_UPDATED / LOCALLY_MODIFIED / MISSING` — that already
   answers "did the child diverge from what was stamped." A hand-maintained `managed:`
   list beside it is a second declaration of one vocabulary, and **by this document's own
   opening argument, the copy will rot.**

The first draft also had a defect it should have caught in itself. This entry:

```yaml
managed:
  - loops.scaffold            # structure only — keys, never `enabled`
```

puts the entire structure-vs-value distinction — the ADR-0143 guard-4 line itself — **in
a YAML comment**, because the entry vocabulary (`loops.scaffold` vs `loops.entries`: two
names for one subtree partitioned by an aspect) could not express it. A document whose
thesis is "structural YAML, never comment markers" carried its most load-bearing rule as
an in-band comment. Its two lists also mixed file paths, dotted keys, and virtual aspects
behind one membership question requiring three different predicates. That is a category
error, and it is the shape that bites.

### What replaces it

Two rules, both enforceable against today's observation surface with no new declaration:

- **The kernel writes `charter.yaml` only at birth.** `scripts/charter_init.py` already
  refuses to overwrite an existing charter; the stamp path gains the same refusal. After
  birth the kernel never writes inside the charter, so there is no sub-file boundary to
  police and **ADR-0143 Ruling 6 guard 4 is satisfied structurally rather than by a
  policed exception.**
- **A new actor file with no `loops` entry is a drift finding filed for a human.** This
  is the existing declared-vs-observed shape of `charter_drift_caretaker`, needing
  nothing `observe_repo` cannot already read. The human adds the entry; the mandate is
  enlarged only by a human commit.

This is *stronger* than "the kernel may refresh the scaffold, structure only," and it
deletes a problem the first draft did not notice it had: **the second enforcement arm
was unimplementable.** "Nothing under `owned` was modified *by a stamp*" is a provenance
claim, and no provenance exists — `observe_repo` (`src/charter_drift_caretaker_loop.py:260-303`)
reads current state only, and `StampResult` is an in-memory return value persisted
nowhere. Checking that arm would have required a committed stamp write-journal plus
pre/post semantic YAML diffs for the dotted keys.

File-level ownership stays where it is: the `Ownership` enum enforced at write, the
kernel lock as the committed record, `make kernel-staleness` as the verifier. If a
repo-voice view of "what the kernel manages" is ever wanted, **render it from the lock** —
never hand-write it beside the lock.

**One rule remains settled by ADR-0143 Ruling 6 guard 4** and is not open for redesign:
the kernel may never enable a loop. Enabling one is the system enlarging its own mandate,
which is an ENACT and belongs to a human. That is also why `charter_init.py` leaves
`purpose` and `articles.local` blank rather than guessing: "guessing them would put words
in the repo's mouth." The same reasoning keeps the `agents/` councils skeleton off by
default.

## "Why not make HydraFlow itself charter-driven?" — measured, and what the number does not prove

HydraFlow's core pipeline, measured on `origin/staging` at `0975fba2a`:

| phase | files | lines |
|---|---|---|
| `triage_phase` | 1 | 780 |
| `plan_phase` | 10 | 3,270 |
| `implement_phase` | 10 | 2,922 |
| `review_phase` | 14 | 5,669 |
| **total** | **35** | **12,641** |

The temptation is to read that as 12,641 lines of workflow waiting to become a YAML file.
It is not. Look at what `plan_phase` decomposed into:

```
_flow  _disposition  _epic  _records  _tiering  _prepass  _adversarial  _wiki_ingest  _common
```

One or two of those dispatch an agent. **The rest is the governance *of* the agent's
work** — which label, which transition, how epic cohorts group and hold an atomic
reservation, how results are recorded, what happens on cancellation. And the prompt half
is already externalised: `src/hydraflow_resources/prompts/auto_agent/*.md`.

**What the number proves and what it does not.** It supports the negative conclusion —
don't YAML-ify HydraFlow's phases — which nobody was proposing. It does **not** support
the positive one. Those 12,641 lines govern *HydraFlow-format code repos*:
`review_phase/_adr.py`, `_ci.py`, `_visual_gate.py`, coverage floors, epic cohort
reservations. None of that applies to a records org whose gate is a human merging
markdown. The genuinely generic outer loop — worktree isolation, PR lifecycle,
escalation, budget, watchdogs, credit handling — lives largely *outside* the measured 35
files.

So the big number is doing rhetorical work in the asymmetry table below. It is honest as
a measurement and misdirected as an argument, and earning the runtime claim requires a
different measurement: **decompose the outer loop into repo-agnostic versus
HydraFlow-format-specific lines.** That work is not done.

| | GNAA | HydraFlow |
|---|---|---|
| actors + loops declared | **yes** | hardcoded |
| outer loop | a human merging a PR | **12,641 lines** (mostly format-specific) |

**Demoted to hypothesis:** that HydraFlow becomes the runtime executing other repos'
charters. It is the interesting direction and it is not established by anything measured
here. It stays a hypothesis until a second, genuinely independent repo — ideally one
whose output is not purely files — survives the schema.

What *is* available now, and is the realistic v1.1.0 shape, is narrower and much cheaper:
**parameterise the agent-facing decisions by charter** — which prompt, which model, what
"done" means, which gates apply — while the orchestration stays code.

## Migration

- `schema_version: 1` charters keep working; `loops` absent means "no charter-declared
  loops", which is what every repo has today.
- `scripts/charter_init.py` gains a `loops:` scaffold with every actor `enabled: false`,
  so a new repo starts with silence declared rather than assumed.
- GNAA migrates by moving `agents/loops.yml` into its `charter.yaml` and replacing
  `bin/lib/loops.py`'s loader with the shared one — **keeping its duplicate-key guard**,
  which the shared loader must have first. Its prose `trigger:` values become clause
  lists; the four conjunctive ones (`incident-ops`, `records`, `outreach-incidents`, and
  the cadence-plus-condition forms) are the migration's real test, and if any cannot be
  expressed, the schema is still wrong.

## Open questions for the operator

1. **Should `goal` support a per-run override?** GNAA's `convene` takes one as argv.
   Useful for dispatch, but it is an input to a governed run. Suggest: allow it, and
   record it — GNAA already writes `operator/run-log.jsonl` receipts, so "unrecorded
   input" is solvable rather than disqualifying.
2. **What happens when an actor file exists and its loop is enabled, but the actor's own
   contract is unparseable?** Suggest: refuse the run, file nothing, alert — never
   degrade to a default prompt.
3. **Is `on:` in v1.1.0 at all?** It is aspirational in the only repo that has it. The
   alternative is shipping `cron` alone and adding `on:` when a detector exists, which
   costs GNAA nothing today since its operator is the detector either way.

## What this is not

Not a scheduler rewrite, and not a new engine. The OPA pilot (#11750) already measured
and rejected adding a policy runtime here; this proposal adds a **declaration surface**
consumed by the Python that already exists.
