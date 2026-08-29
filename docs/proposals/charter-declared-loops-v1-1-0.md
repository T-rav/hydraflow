# Charter-declared loops — the repo owns the workflow, the factory owns governance

**Status:** Proposal · targets v1.1.0 · `charter.yaml` `schema_version: 2`
**Date:** 2026-08-29
**Relates:** ADR-0143 (PAAA), ADR-0121 (the manifest), ADR-0042 (two-tier promotion), #11748 (charter.yaml), #11035 (cognitive-process manager)

## The idea in one line

A repo declares **what agents it has and when they should run**; HydraFlow runs the
**outer loop** — isolation, PR lifecycle, gates, escalation — for every repo without
reimplementing any of it per repo.

## This is not speculative — it already runs

`T-rav/goodneighboraviation.org` built this pattern independently, and further than
expected:

```
agents/<name>.md              the charter IS the agent — role definition and prompt in one file
agents/{board,council,operator}/
agents/loops.yml              enabled · trigger · goal — the repo's own loop registry
bin/convene <agent> [goal]    ONE generic runner. No per-loop code.
output = branch + PR          bin/convene's own header: "the merge is the gate"
.github/workflows/convene.yml the outer loop, such as it is
```

Thirteen markdown charters and one YAML file, with no Python per loop. Its governance
is "open a PR and let a human merge it" — which is correct, and is also exactly the
half HydraFlow already has industrialised.

**The two halves are already shaped to fit.** `charter.yaml` declares `actors: agents/`.
GNAA *has* `agents/`. Neither was built for the other.

## The constraint that shapes the design

`src/charter.py:27`:

```
actors: agents/                           # pointer ONLY, never a role list
```

This is enforced — `_parse_actors` raises `CharterError` on a role list, per ADR-0143
Ruling 6. The reason is not stylistic: a roster in the charter plus a directory of
actor files is **two tables over one vocabulary**, the same defect that shipped as the
dual `Charter` classes (`src/charter.py:416` and `src/policy/models.py:133`, whose
`articles.standards` fields overlap on exactly one id).

So `loops.yml` **cannot** simply move into `charter.yaml` as a roster. The contract must
declare *behaviour keyed on actors*, with the actors themselves still derived from the
directory.

## The contract

`charter.yaml`, `schema_version: 2`:

```yaml
schema_version: 2

actors: agents/                    # UNCHANGED. Still a pointer, never a roster.

loops:                             # NEW. Behaviour per actor — not a roster.
  finance:                         # key MUST resolve to agents/finance.md
    enabled: true                  #   or agents/finance/README.md
    trigger:
      cron: "0 9 1 * *"            # xor `on: <event>` — exactly one
    goal: >
      Produce the monthly close per your output contract from the ledger in
      this repo.
    output:
      branch_prefix: "finance/"
      gate: pr                     # the merge is the gate

  correspondence:
    enabled: true
    trigger:
      on: inbound_received
    goal: Triage all new inbound per contract.

  dormant:                         # explicit, so silence is never the default
    - pr                           # an actor with no loop must say so here
    - meeting
```

### Field notes

- **`goal` is the run's task inside the charter, not a replacement for it.** GNAA's
  framing — "the charter is the agent; the goal is the run's task inside it" — is the
  right one and should survive the move.
- **`trigger` is `cron` xor `on`.** GNAA's current `trigger:` is prose
  (`"weekly · and on each telemetry candidate"`), which is readable and unschedulable.
  A machine-read trigger has to be one or the other, and the loader should reject both
  or neither.
- **`gate: pr`** is the only value at v1.1.0. It names what already happens rather
  than inventing policy.

## Three guards, each earned by a real failure

**1. Bidirectional resolution.** Every `loops` key resolves to an actor file, *and*
every actor file appears in `loops` or in `dormant`. One-way binding is how
`standard.yaml` and its README drifted until #11751 bound them; the fix there was a
both-directions assertion and it is the same fix here.

**2. A mis-parse must fail LOUD, never "dormant."** GNAA's `bin/convene` parses
`loops.yml` with a regex inside a heredoc:

```python
m = re.search(rf"^  {re.escape(agent)}:\s*\n((?:^    .*\n|^  \{{.*\n)*)", text, re.M)
...
if "enabled: true" not in block: sys.exit(1)   # -> "agent is dormant"
```

Any YAML shape the pattern did not anticipate reads as **not enabled**, and the agent
silently does not run. That is a governance system whose failure mode is silence, and it
is the same class as the fifteen narrow-predicate guards found in this repo on
2026-08-29 — each one narrower than the vocabulary of the thing it described.

The loader must be a real YAML load, schema-validated, raising `CharterError` on
anything unexpected. **An unparseable loops block is an error, never an absence.**
`src/charter.py` already draws this distinction correctly for the charter as a whole —
`load_charter` returns `None` only for a repo with *no* charter — and the same rule must
hold one level down.

**3. Empty is not absent.** A present-but-empty `loops:` block declares that nothing
runs. A missing block means an unmigrated repo. The caretaker skips the second and must
not skip the first.

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
2. Select due loops (`enabled` and `trigger` fired).
3. For each: create an isolated worktree, render the actor's charter file as the system
   prompt with `goal` as the task, dispatch one brokered worker.
4. Hand the output to the existing gates — branch, PR, labels, review, merge policy.
5. Record a receipt.

Steps 1–3 are new. Steps 4–5 already exist and are the reason this is worth doing.

## "Why not make HydraFlow itself charter-driven?" — measured

The obvious next question, and the answer is a number rather than an opinion.

HydraFlow's core pipeline, measured on `origin/staging` at `0975fba2a`:

| phase | files | lines |
|---|---|---|
| `triage_phase` | 1 | 780 |
| `plan_phase` | 10 | 3,270 |
| `implement_phase` | 10 | 2,922 |
| `review_phase` | 14 | 5,669 |
| **total** | **35** | **12,641** |

The temptation is to read that as 12,641 lines of workflow waiting to become a YAML
file. It is not. Look at what `plan_phase` decomposed into:

```
_flow  _disposition  _epic  _records  _tiering  _prepass  _adversarial  _wiki_ingest  _common
```

One or two of those dispatch an agent. **The rest is the governance *of* the agent's
work** — which label, which transition, how epic cohorts group and hold an atomic
reservation, how results are recorded, what happens on cancellation. And the prompt half
is already externalised: `src/hydraflow_resources/prompts/auto_agent/*.md`.

So the 12,641 lines are not HydraFlow's *implementation* of a workflow. **They are the
outer loop.** GNAA's `bin/convene` is a single file precisely because GNAA has none of
it — its entire governance is "open a PR, a human merges."

**The conclusion this forces is one level up from where the idea starts:** HydraFlow does
not become a charter-driven repo. It becomes **the runtime that executes other repos'
charters.** Its phase logic is the product, not the thing to be replaced.

What *is* available, and is the realistic v1.1.0 shape, is narrower and much cheaper:
**parameterise the phases by charter for the agent-facing decisions** — which prompt,
which model, what "done" means, which gates apply — while the orchestration stays code.
That is what lets one factory serve many repos without a rewrite.

The asymmetry is the whole argument for doing this at all:

| | GNAA | HydraFlow |
|---|---|---|
| actors + loops declared | **yes** | hardcoded |
| outer loop | a human merging a PR | **12,641 lines** |

Each has exactly what the other lacks.

## Migration

- `schema_version: 1` charters keep working; `loops` absent means "no charter-declared
  loops", which is what every repo has today.
- `scripts/charter_init.py` gains a `loops:` scaffold with everything `dormant`, so a new
  repo starts with silence declared rather than assumed.
- GNAA migrates by moving `agents/loops.yml` into its `charter.yaml` and replacing
  `bin/convene`'s regex with the shared loader. Its `trigger:` prose becomes `cron`/`on`.

## Open questions for the operator

1. **Does `dormant` belong in the charter, or is absence-from-`loops` enough?** Explicit
   is louder and costs a line per actor; the argument for it is that silence should never
   be the default in a governance file.
2. **Should `goal` support a per-run override?** GNAA's `convene` takes one as argv. Useful
   for dispatch, but it is an unrecorded input to a governed run.
3. **What happens when an actor file exists and its loop is enabled, but the actor's own
   contract is unparseable?** Suggest: refuse the run, file nothing, alert — never
   degrade to a default prompt.

4. **How does re-hydration treat a `loops:` block?** This is the one that needs
   deciding before implementation, because the existing mechanism does not reach it.

   The kernel writer already separates template from product with a four-state action
   model (`written | rewritten | skipped | protected`) and an **in-file boundary
   marker**:

   ```
   <!-- writer never overwrites anything below this marker. -->
   ```

   That works for markdown. **YAML has no equivalent convention here**, so a
   `loops:` block in `charter.yaml` currently has no way to say "the kernel owns this
   half, the repo owns that half." Two options, and they are genuinely different:

   - **`loops:` is wholly product.** The kernel stamps it once at greenfield hydration
     and never again; re-stamping skips the file entirely, as `charter_init.py` already
     does (it "refuses to overwrite an existing charter, and is never wired into a
     loop"). Simple, and consistent with today's behaviour — but a repo never receives
     schema improvements to its loops block.
   - **YAML gains a boundary convention** — a `# hydraflow:managed` / `# hydraflow:end`
     pair, or a nested `managed:` key. Lets the kernel keep a scaffold current while the
     repo owns the entries. More capable, and one more parser that can drift from its
     subject.

   **Recommended: the charter declares its own hydration boundary.** Neither option
   above is right, because both put the rule somewhere other than the file it governs —
   a comment convention the kernel has to parse, or an implicit "never touch this"
   nobody can read. The charter is the repo's *governing declaration*; it should
   therefore declare who governs which part of it:

   ```yaml
   hydration:
     managed:                      # the kernel may refresh these on re-stamp
       - loops.scaffold            #   structure only — keys, never `enabled`
       - artifacts.required
     owned:                        # the kernel never writes these, ever
       - purpose
       - articles.local
       - loops.entries
   ```

   This is better than a marker for three reasons, each drawn from something that has
   already gone wrong here:

   - **It is readable by the repo owner**, not just by the writer. A
     `<!-- do not edit below -->` marker states the rule in the kernel's voice; a
     `hydration:` block states it in the repo's.
   - **It is checkable in both directions.** `charter_drift_caretaker` can assert that
     everything the kernel wrote is under `managed`, and that nothing under `owned` was
     modified by a stamp. A comment marker can only be honoured, never verified — and
     an unverifiable boundary is the shape of every guard this repo found watching
     nothing.
   - **It makes the ENACT/RATIFY line explicit rather than implicit.** Today the rule
     that a kernel may not enable a loop lives in an ADR and in `charter_init.py`'s
     docstring. Under this scheme it is a fact in the repo's own file, and a stamp that
     violates it is a drift finding rather than a code review someone has to catch.

   The cost is honest: `hydration` is one more declaration that can drift from what the
   kernel actually does. That is precisely why it must be enforced by the drift caretaker
   from the first commit, with a negative control proving the check can fail — not
   documented and trusted.

   Whichever is chosen, **one rule is already settled by ADR-0143 Ruling 6 guard 4** and
   is not open for redesign: the kernel may stamp the *structure* — a `loops:` block with
   every actor `dormant` — but it may **never enable a loop**. Enabling one is the system
   enlarging its own mandate, which is an ENACT and belongs to a human. That is also why
   `charter_init.py` leaves `purpose` and `articles.local` blank rather than guessing:
   "guessing them would put words in the repo's mouth."

   The same reasoning explains why the `agents/` councils skeleton is off by default —
   "chartering review chambers is a deliberate project choice, not kernel plumbing." A
   loops block is the same kind of choice.

## What this is not

Not a scheduler rewrite, and not a new engine. The OPA pilot (#11750) already measured
and rejected adding a policy runtime here; this proposal adds a **declaration surface**
consumed by the Python that already exists.
