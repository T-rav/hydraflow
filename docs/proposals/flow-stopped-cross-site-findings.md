# `_flow_stopped` cross-site findings: identical definitions, conditional unification

**Status:** findings note, prerequisites incomplete (2026-08-30). **Issue:** #11808 (child of epic
#11804, itself scoped by #11798/#11797's concept-scatter sensor finding, #10106/#10104).
**Verdict:** all three definitions are **identical** (byte-for-byte body/signature/docstring, and
semantically — same input contract, same pure logic, no side effects). Unification is **safe,
conditional** on landing test evidence first; see [Evidence gap](#evidence-gap-read-before-trusting-this-note).

## Evidence gap — read before trusting this note

This issue's stated scope is to *consume* capture notes and characterization tests from three
prerequisite children — #11805 (plan), #11806 (implement), #11807 (review). As of this analysis
(repo HEAD `cdced8e6`), **none of the three have landed**: all three are still `OPEN`, none has a
PR, and no capture note or characterization test exists anywhere in the repo. This was already
flagged once by the triage bot (issue comment, 2026-08-30T10:11:14Z) and the retry budget has not
produced the missing artifacts.

Per the issue's own anti-stall guidance ("if evidence is insufficient for a pair, mark the verdict
'insufficient evidence — list gap' and stop; do not fabricate a safe-to-unify conclusion"), the
honest gap is: **there are no characterization tests pinning current behavior**, so nothing formally
guards a future unification PR against silently changing routing behavior in any one phase.

What this note *can* stand on: the constraint is read-only, reversible source inspection at HEAD,
which is a strictly stronger form of evidence than eyeballing a diff (the same manual check the
triage bot did for a single pair) — it reads the full definition, docstring, every call site, every
`state["_stop"]` write, and the shared `Flow`/`Edge` runtime all three depend on. That is enough to
answer "are these identical / drifted / distinct" with high confidence. It is **not** enough to
certify that no phase silently relies on `_flow_stopped` behaving differently in some untested edge
case (e.g. a `state` shape violation) — that is exactly what characterization tests are for. The
per-pair verdicts below reflect that: "unification safe" is conditional on the three children still
landing before any actual migration PR, not on this note alone.

## The three definitions, verbatim

| Site | Location |
|---|---|
| Plan | `src/plan_phase_common.py:37-39` |
| Implement | `src/implement_phase/_common.py:51-53` |
| Review | `src/review_phase/_flow.py:106-108` |

```python
def _flow_stopped(state: FlowState) -> bool:
    """Edge guard: a node signalled a fail-closed early exit → route to ``done``."""
    return bool(state.get("_stop"))
```

Confirmed textually identical — signature, docstring, and body — across all three files, character
for character. All three type-hint `state` as `FlowState`, which is the *same* shared type
(`FlowState = dict[str, Any]`, `src/flows/flow.py:43`) — not three independently-defined lookalike
types. `_flow_stopped` is a pure function: no I/O, no mutation, no phase-specific keys, no config
threshold. There is no parameterization to drift — either the three bodies match or they don't, and
they match.

## Origin: one flow-DAG refactor series, relocated by three later decompositions

Epic #11797 describes the sensor finding as `_flow_stopped` being "independently introduced in
three modules in a single merged change (`53b4905..5402592`)." Direct history check (`git log
--format='%h %ad %s' --date=short -S'def _flow_stopped(state: FlowState) -> bool:' --all --
src/`) shows the opposite of independent introduction: the function was written **once per
phase, by a single four-PR series**, on one day, then merely relocated by three later,
unrelated PRs.

**Introduction — 2026-07-26, the #10682 flow-DAG (ADR-0111) rollout, four commits ~2.5 hours
apart, same author:**

- `c5fecf36` (13:36) — refactor(implement): run implement as a flow (DAG) + no-progress abort (P2 of #10682) (#10694) → wrote `_flow_stopped` into `src/implement_phase.py`
- `5ff50054` (14:23) — refactor(plan): run plan as a flow (DAG) on the primitive (P3a of #10682) (#10696) → wrote it into `src/plan_phase.py`
- `48e918ab` (15:23) — refactor(review): run review as a flow (DAG) on the primitive (P3b of #10682) (#10700) → wrote it into `src/review_phase/_phase.py`
- `e1c0336e` (16:06) — refactor(triage): run triage as a flow (DAG) on the primitive (P3c of #10682) (#10702) → wrote it into `src/triage_phase.py` (the fourth, out-of-scope site — see [Scope note](#recommendation))

Each of these four commits re-expresses that phase's worker body on the `src/flows` `Flow`
primitive per ADR-0111, and each one hand-writes the same four-line guard as part of that
rewrite — one author applying one template four times in an afternoon, not four people
independently converging on identical code.

**Relocation — 2026-08-21/22, three unrelated god-class decompositions, nearly a month later:**

- `ab3e5d18` (08-21) — refactor(pr-manager,review-phase): decompose two god classes below the mass threshold (#11628) → moved the review site from `review_phase/_phase.py` to `review_phase/_flow.py`
- `2f440e80` (08-22) — refactor(orchestrator,plan-phase): decompose two god classes below the mass threshold (#11645) → moved the plan site from `plan_phase.py` to `plan_phase_common.py`
- `1dfa9210` (08-22) — refactor(implement,mockworld): decompose ImplementPhase and FakeGitHub into mixin packages (#11658) → moved the implement site from `implement_phase.py` to `implement_phase/_common.py`

These three PRs are not introductions, they are moves: each commit message and diff backs the
"VERBATIM" claim `plan_phase_common.py`'s docstring already makes — `2f440e80` reports 57/57
`PlanPhase` method bodies AST-identical before/after, `1dfa9210` reports 0 missing/0 extra/0
changed across 61+133 methods, `ab3e5d18` reports the same shape for `ReviewPhase`. None of the
three diffs touches `_flow_stopped`'s logic; they relocate the existing four lines into a
`_common`/`_flow`/mixin module so sibling mixins can import them without an import cycle back
through the parent phase file — a decomposition-pattern constraint, not a behavioral one.

**Epic #11797's `53b4905..5402592` range is the relocation window, not the introduction
window.** That range brackets the three August decompositions, which is why the sensor observed
three near-simultaneous appearances of `_flow_stopped` at new file paths — the guard itself was
already a month old at that point, having lived in `plan_phase.py`, `implement_phase.py`, and
`review_phase/_phase.py` since the July 26 flow-DAG rollout. "Three modules in a single merged
change" describes where the code landed, not when or how many times it was written.

This origin reinforces the identical-classification below rather than complicating it: there is
no independent-introduction story to reconcile against the byte-identical bodies. A single
template was written four times on 2026-07-26 by one author in one refactor series, then carried
verbatim — by three separate but equally mechanical relocations — into the files this issue
compares.

## Usage context per site

All three sites wire `_flow_stopped` into a `src/flows/flow.py` `Flow` graph as a gate-node `Edge`
guard, using the identical idiom (identical comment, too: `# First-match-wins: a stopped node skips
straight to the sink.`) — first-match-wins routing to a terminal `done` node when `state["_stop"]`
is truthy. The *mechanism* is identical at every call site; what differs is which gate nodes in each
phase's graph use it, because the three flows have different shapes:

| Phase | Gate nodes wired to `_flow_stopped` → `done` | Gate nodes NOT wired to it |
|---|---|---|
| Plan (`plan_phase_flow.py`) | `prepass`, `route`, `gate` (3) | — |
| Implement (`implement_phase/_flow.py`) | `decompose`, `no-progress-abort`, `issue-state`, `zero-commit-abort` (4) | `gate` (unconditional → `done`); `screen` (routes on `_route_is_zero_commit`/`_route_is_failure_screen`); `open-pr` (routes on `_open_pr_terminal`) |
| Review (`review_phase/_flow.py`) | `guards`, `pre-review` (2) | `gate` (routes on `_approve_path_handled`) |

This is a difference in **how many places each phase chooses to check the guard**, driven by each
flow's own shape (implement's zero-commit-abort branch, review's approve/reject gate), not a
difference in what the guard itself does. Every site that *does* call `_flow_stopped` calls it with
the same contract and gets the same answer for the same state. `state["_stop"] = True` is set at
8 sites in plan (7 in `plan_phase_flow.py`, 1 in `plan_phase_tiering.py`), 7 in implement, 2 in
review (`grep -rn` at HEAD) — phase-specific fail-closed exits, each also setting a phase-specific
`result` the `done` node reads — but that's what triggers the guard, not what the guard does.

## Per-pair verdicts

### Plan ↔ Implement
- **Classification: identical.** Byte-identical body/signature/docstring; identical `FlowState`
  contract; identical routing idiom. Only the *number* of gate nodes each flow wires to it differs
  (3 vs 4), which is a property of each flow's shape, not of the guard.
- **Unification safe? Conditional — yes**, pending the characterization tests from #11805/#11806
  landing to formally pin both phases' current routing behavior before a shared definition replaces
  either local one.

### Plan ↔ Review
- **Classification: identical.** Same basis as above (3 vs 2 gate nodes wired).
- **Unification safe? Conditional — yes**, pending #11805/#11807.

### Implement ↔ Review
- **Classification: identical.** Same basis as above (4 vs 2 gate nodes wired; review's `gate` node
  additionally branches on a non-`_flow_stopped` guard, `_approve_path_handled` — routing to
  `cleanup` directly on the approve path, or via `route` → `cleanup` otherwise, with `done` reached
  only downstream of `cleanup` — where implement's analogous `gate` node has a single unconditional
  `gate` → `done` edge and no equivalent guard).
- **Unification safe? Conditional — yes**, pending #11806/#11807.

## Recommendation

Divergence is **not** intentional — there is no divergence to explain; the three bodies are
identical and the differences are all in caller-side wiring, which a shared definition would not
touch. This resolves the epic #11797 sensor finding's open question ("may be genuinely identical...
or may have drifted semantically") in favor of **genuinely identical**.

A shared definition has a natural, cycle-safe home: `src/flows/flow.py` already defines `FlowState`,
`Edge`, and `Flow`, and all three current sites already depend on that module for `FlowState`. Adding
`_flow_stopped` there (or a sibling `flows/guards.py`) introduces no new import edge and does not
reintroduce the mixin-cycle problem the original "VERBATIM" extractions were designed to avoid — that
constraint was about phase mixins not importing each other or their parent phase file, not about
depending on the shared `flows` package.

**Before executing unification:** land #11805/#11806/#11807's characterization tests so the
migration PR has behavior-pinned regression coverage per phase, not just this note's static-read
comparison. This note clears the judgment call; it does not substitute for the test evidence the
epic asked for.

**Scope note:** a fourth textually-identical `_flow_stopped` exists at `src/triage_phase.py:127`,
outside this issue's three-way comparison scope (plan/implement/review only, per the issue body). A
real unification pass should sweep this fourth site too rather than leave it as a residual
duplicate — flagged here for the epic, not addressed by this synthesis child.
