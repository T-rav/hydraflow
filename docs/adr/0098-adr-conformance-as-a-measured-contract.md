# ADR-0098: ADR conformance as a measured contract

**Status:** Accepted
**Date:** 2026-06-30
**Enforcement:** enforced
**Enforced by:** pytest:tests/test_adr_conformance_coverage.py

## Context

HydraFlow has a **dependency** link between an ADR and the code it governs: `adr_drift.py` cites modules and trips a tripwire when they change (ADR-0056). It does not have a **conformance** link: a way to ask "does the decision still hold?" and get a machine answer. ADR-0093 pioneered a one-off `**Enforced by:**` frontmatter line pointing at a test, but that line was unparsed, unvalidated, and rendered nowhere — a convention by convention, not by construction.

This matters because agents read Accepted ADRs as ground truth. `adr_index.render_full` injects ADR prose directly into plan-phase prompts. An ADR whose invariant has silently drifted is worse than no ADR at all: it is a confidently wrong instruction. The fitness-function pattern is already proven three times over in this repo (wiki `json:entry` blocks, ADR source-citations, the `loop_fitness` ratchet from ADR-0093). The one architectural layer without a conformance contract is the ADRs themselves, the decisions everything else defers to.

This ADR **supersedes** the pre-existing "P3" `**Enforced by:**` convention introduced by PR #8398: a bare `**Enforced by:**` line (values like `(none)`, `(process)`, `(historical)`) validated only by `tests/test_adr_enforcement.py`, with no typed grammar and no resolution check. That test is deleted; `tests/test_adr_conformance_coverage.py` is the single validator going forward, and the `**Enforced by:**` line is now paired with a required `**Enforcement:**` kind (`enforced` / `manual` / `decision-of-record`) instead of standing alone.

## Decision

### The contract surface

Every Accepted ADR (outside a shrinking grandfather list) declares an `**Enforcement:**` kind and, where required, an `**Enforced by:**` list of typed-prefix checks (`pytest:`, `make:`). The three kinds map onto ADR-0093's `FitnessKind`: `enforced` (asserts a runnable invariant) is the `SCORED` analogue, `decision-of-record` (a choice with no runtime predicate) is the `HOUSEKEEPING` analogue, and `manual` (a real guardrail that is human-verified, not machine-run) sits as a new middle kind with no equivalent in the loop-fitness lattice. An unrecognized or absent value normalizes to `unknown`, which fails the ratchet. Executed checks must be side-effect-free: a check that mutates the repo would have the very act of measuring conformance rewrite files, which violates the purity spirit this ADR inherits from ADR-0093.

### Two seams, two lifecycle points

The parsed `Enforcement` / `Enforced by` fields are read by two independent seams that never depend on each other's output:

1. **The coverage ratchet** (`tests/test_adr_conformance_coverage.py`) is a **pre-merge, CI-blocking PR gate**. It never executes a check; it resolves each one by AST/file inspection — a `pytest:` node's file exists and defines the function or class, a `make:` target is present in the `Makefile` and is not on the mutating-target denylist. A green PR proves every declared link resolves and is safe to run.
2. **`AdrConformanceLoop`** (ADR-0029 caretaker shape) is a **post-merge drift watch** on `main`. On a slow cadence it actually executes each `enforced` ADR's checks, persists PASS/FAIL/UNRESOLVED results to `.hydraflow/metrics/{repo_slug}/adr_conformance.jsonl`, regenerates `docs/arch/generated/adr-conformance.md`, and emits `ADR_CONFORMANCE_UPDATE`.

The ratchet proves the wiring is sound at merge time; the loop proves the decision still holds over time. Neither one can substitute for the other: a check that resolves can still fail once the code around it drifts, and a check that fails once can still resolve.

### Split-class remediation

A red check has more than one plausible cause, and the loop does not guess which:

- `UNRESOLVED` with a confirmed rename (the named check exists under a new identity: an identical test node moved, a target renamed) is handled by filing a dedup'd issue that proposes the re-point — the loop computes the new `Enforced by:` identity but does not edit the ADR itself; a human or the pipeline applies it. No confident match means the guardrail was deleted, not moved, and the outcome is treated as `FAIL`.
- `FAIL` on first occurrence files one dedup'd remediation issue with pipeline labels, the same way any other pipeline defect enters the system (ADR-0002).
- `FAIL` that recurs past a per-ADR attempt budget (default 3 attempts, reusing `ConvergenceLedger` oscillation semantics) flips interpretation: the pipeline's repeated inability to conform the code is evidence that the decision itself, not the code, is the problem. That case escalates to `adr_reviewer` as a supersession proposal.

The ambiguity between "code drifted" and "decision moved on" is real and the loop does not resolve it by classification — a `FAIL` exit code cannot distinguish the two causes. It resolves it by recurrence: assume conform-the-code on the first failure, and only promote to supersession-candidate once that assumption has been tested and has failed repeatedly. This is the same posture ADR-0046 takes toward "who decides the watcher is wrong": termination by an external, bounded process, not by an internal guess.

### The no-rubber-stamping guardrail (load-bearing)

A red conformance check has exactly two legitimate ways to go green: the code is fixed, or a human/reviewer supersedes the decision. There is an illegitimate third way — weaken the check or quietly relax the ADR's own fields — and this ADR makes that path structurally unavailable rather than merely discouraged.

`AdrConformanceLoop`'s entire write surface is three kinds of GitHub issue: an issue proposing a re-point of `Enforced by:` on a confirmed rename, a remediation issue (filed or updated), and an `adr_reviewer` supersession proposal. It never edits repo files: no code path touches a check's assertion body, an ADR's `Enforced by:` line, or an ADR's `Enforcement:` / `decision-of-record` fields, and a unit test asserts the loop cannot mutate any file under `src/`, `tests/`, or `docs/`. The jsonl it persists is gitignored scratch state, not a decision artifact. Nothing in this design lets the loop mark itself green by softening what green means.

### `AdrConformanceLoop` is on the ADR-0046 recursion ladder

`FitnessScorecardLoop` (ADR-0093) is read-only: it observes and mutates nothing, so ADR-0046's "who watches the watcher" question does not apply to it — there is no behavior change for a meta-observer to bound. `AdrConformanceLoop` is different in kind: it **mutates** by filing GitHub issues (never by editing repo files). That makes it a producer in the ADR-0046 sense, and it sits **on** the recursion ladder rather than beside it. It is bounded the same way every other mutating caretaker loop is bounded: the state rollup (`get_adr_conformance_rollup` / `set_adr_conformance_rollup`) caps it at one open remediation issue per ADR by gating create-vs-update on the recorded issue number, a per-ADR attempt budget caps how long it keeps re-filing before escalating to supersession, and `enabled_cb("adr_conformance")` (ADR-0049) is the kill switch that stops it outright. A `DedupStore` entry is also written alongside the rollup as a secondary dedup marker, consistent with the sibling `AdrTouchpointAuditorLoop`, but it is not the operative suppression gate. No new recursion-termination mechanism was invented for this loop; it reuses the ladder's existing rungs.

## Consequences

- Every Accepted ADR outside the grandfather list must declare a resolving `Enforcement`. The grandfather list is committed and monotonically shrinking (`test_grandfather_only_shrinks` fails CI on any growth), so backfill is incremental and cannot be dodged by widening the exemption.
- `enforced` checks must be side-effect-free. A mutating make target (e.g. `lint-ul`, `arch-regen`) cannot be cited; a `--check`-mode variant must exist or be written.
- The dependency tripwire (ADR-0056, `adr_drift.py`) and the conformance contract (this ADR) are complementary, not redundant: one flags that governed code changed, the other proves the governing decision still holds.
- `AdrConformanceLoop` is a mutator on the ADR-0046 ladder, so any future audit of "which loops need dedup + attempt-budget + kill-switch bounding" must include it alongside the other producer loops, not alongside the read-only observers.
- This ADR is itself Exhibit A: it is `enforced`, cites `tests/test_adr_conformance_coverage.py`, and its own coverage entry is proved the same way as every other ADR the ratchet checks — no ADR earns a manual exemption from the mechanism it defines.
- The P3 `**Enforced by:**`-only convention (PR #8398) and its validator `tests/test_adr_enforcement.py` are retired. `docs/adr/README.md`'s Enforcement section and every future Accepted ADR use the `**Enforcement:**` + `**Enforced by:**` pairing this ADR defines.

## References

- [ADR-0093](0093-loop-fitness-as-measured-contract.md) — Loop fitness as a measured contract. Sibling ADR and structural template; `FitnessKind` is the lattice `Enforcement` kinds map onto.
- [ADR-0056](0056-adr-touchpoint-gate-to-caretaker-loop.md) — ADR touchpoint gate. The dependency tripwire (`adr_drift.py`) this conformance contract complements: one watches for code change, the other watches for decision drift.
- [ADR-0029](0029-caretaker-loop-pattern.md) — Caretaker Background Loop Pattern. `AdrConformanceLoop` follows this shape: `BaseBackgroundLoop` extension, gated `_do_work()`, stats-dict tick.
- [ADR-0049](0049-trust-loop-kill-switch-convention.md) — Trust-loop kill-switch convention. `AdrConformanceLoop._do_work()` gates on `enabled_cb("adr_conformance")`.
- [ADR-0046](0046-meta-observability-bounded-recursion.md) — Meta-observability with bounded recursion. `AdrConformanceLoop` mutates, so unlike `FitnessScorecardLoop` it sits on the recursion ladder, bounded by dedup, attempt budget, and the kill switch.
- [ADR-0002](0002-labels-as-state-machine.md) — Labels as state machine. Remediation issues enter the pipeline the same way any other defect does: through labels.
- `src/adr_index.py` — parse host for `Enforcement` / `Enforced by`.
- `tests/test_adr_conformance_coverage.py` — the CI-blocking coverage ratchet (this ADR's own enforcement).
- `src/adr_conformance.py` / `src/adr_conformance_loop.py` — pure result model and producer loop.
