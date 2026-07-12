# ADR-0105: Autonomous Convergence via Decomposition

- **Status:** Proposed
- **Date:** 2026-07-12
- **Supersedes:** none
- **Superseded by:** none
- **Amends:** [ADR-0084](0084-auto-agent-universal-root-cause-gate.md) (Auto-Agent as a Universal, Persistent, Root-Cause HITL Gate) — keeps its architecture, interception model, AND its terminal `human-required` hand-off; inserts an autonomous **decomposition** step *before* that terminal, so `human-required` fires only for the genuinely unmergeable / undecomposable dead-end.
- **Related:** [ADR-0002](0002-labels-as-state-machine.md) (label state machine); [ADR-0050](0050-auto-agent-hitl-preflight.md) (auto-agent pre-flight loop); [ADR-0029](0029-caretaker-loop-pattern.md) (caretaker loop pattern); [ADR-0044](0044-hydraflow-principles.md) (recursion safety); [ADR-0051](0051-iterative-production-readiness-review.md) (iterative review convergence); [ADR-0059](0059-advisor-pattern-self-repairing-review.md) (advisor / council pattern); [ADR-0032](0032-per-repo-wiki-knowledge-base.md) (wiki knowledge base informing the council).
- **Enforced by (planned):** `tests/test_issue_decomposer.py`; `tests/test_decomposition_council.py`; `tests/test_auto_agent_decompose_terminal.py`; `tests/test_decomposition_depth_cap.py`; `tests/scenarios/test_decompose_to_converge_scenario.py`; `tests/sandbox_scenarios/scenarios/s54_decompose_to_converge.py`.

## Context

[ADR-0084](0084-auto-agent-universal-root-cause-gate.md) made the Auto-Agent a universal gate that intercepts `hitl-escalation` issues, attempts an autonomous fix, and pages a human only for genuinely novel failures. Its terminal, when the auto-agent's own budget (`auto_agent_max_attempts`, default 3) is spent, is to stamp **`human-required`** (`auto_agent_preflight_loop.py:180`, `preflight/decision.py:96`) — a human-owned state.

In practice the gate escalates **too often**: a change that is merely *too broad or ambiguous* to converge as one unit hits an attempt cap and pages a human, when it should have been broken into tractable pieces the factory can finish itself. That is routine toil, not a real request for help.

The operating requirement: **eliminate routine human escalation, and reserve `human-required` for the genuinely unmergeable / undecomposable dead-end** — the case where the factory truly is stuck and a human *should* step in (a real bug it can't fix, a missing external dependency, ambiguous intent no split resolves, a broken factory). HITL is correct there; it is wrong for a change that only needed splitting.

The lever HydraFlow already has for "too big to converge as one unit" is **decomposition**: `Triage.run_decomposition` already splits an issue into an epic + 2–6 child specs, and `EpicCompletionChecker`/`EpicSweeperLoop` already auto-close a parent when its children merge. Today that path fires only on **intake complexity**, never on **retry exhaustion** — so a stall that a split would fix escalates to a human instead.

## Decision

When a change exhausts the auto-agent's budget, **try to decompose it into smaller child issues before paging a human**. If it splits, the parent converges when its children converge (no human). If it cannot split, it falls through to ADR-0084's existing `human-required` terminal — now reached only for the genuine dead-end. This inserts a step; the interception model, retry semantics, and playbooks are unchanged.

1. **Insert decompose before the terminal.** At the two `human-required` sites, first attempt decomposition. `human-required` is applied only when decomposition is declined or exhausted — so it survives as the honest "factory is stuck, needs a human" signal, no longer fired for merely-too-big changes.

2. **Council-based, doc-informed decomposition.** The split is decided by a **council**, not a single LLM shot — reusing the established council / advisor pattern (cf. the ADR-review council in `adr_reviewer.py`, `ExpertCouncil`, ADR-0059). Two passes:
   - **Direction** — propose candidate slicings from distinct lenses (architectural / layer boundaries; isolate-the-failing-part; vertical independently-shippable slices), given the **stall context** (failing stage, `blocked_reason`, diagnosis, diff-so-far, review findings).
   - **Validation** — judge the chosen split: are the children independently-shippable, non-overlapping, genuinely *more tractable* than the parent (not clones), and consistent with the architecture? If no sound split survives, the council **declines** (`should_decompose = false`) → the HITL floor.

   The council is **informed by the docs**: the relevant ADRs (resolved from the change's touched files via the ADR cross-reference) and the relevant wiki entries (patterns / gotchas / testing for the affected area, per [ADR-0032](0032-per-repo-wiki-knowledge-base.md)) are fed into its context, so the slicing respects accepted architectural decisions and reuses accumulated knowledge instead of re-deriving it. Extract the create/link/register plumbing from `TriagePhase._maybe_decompose` into a standalone `IssueDecomposer` the council drives; the existing single-shot `Triage.run_decomposition` stays the intake path.

3. **Reuse the epic machinery.** On `should_decompose = true`: create the epic + children (children enter at `hydraflow-find` and run the full pipeline), `register_epic(auto_decomposed=True)`, then close the stuck issue as `decomposed`, close its superseded PR, and let `workspace_gc_loop` reap its worktree — the exact terminal pattern intake decomposition already uses. Parent rollup is free (`EpicCompletionChecker` + `EpicSweeperLoop`).

4. **Bounded depth (moderate budget).** A new `max_decomposition_depth` (default 2) caps recursion: a decomposed child that also stalls may split once more, then hits the floor. Depth is tracked per epic/child. The pre-decompose retry caps (implement 3 / review 2 / auto-agent 3) are unchanged — they are the "fair shot" before a split.

5. **The floor: HITL, for the genuine dead-end.** When `should_decompose = false` (not decomposable) OR depth is exhausted, fall through to ADR-0084's `human-required` terminal + a full diagnostic comment. This is the *correct* use of HITL — the factory has exhausted its autonomous options (retries, auto-agent, decomposition) on a change that is neither mergeable nor splittable, so a human genuinely needs to step in. The change from today is **selectivity, not removal**: HITL becomes rare and meaningful instead of routine.

## Consequences

- **HITL becomes rare and meaningful.** A pipeline change reaches merged, decomposed→merged, or — only when neither is possible — `human-required` with a diagnostic. The routine "too-big → human" escalations are gone; the ones that remain are genuine "factory is stuck, needs help" signals, which is exactly what HITL is for.
- **Correct use of the human.** Decomposition turns *too-big / ambiguous* into *tractable*; it cannot manufacture a merge for a genuinely-impossible change (real bug it can't fix, missing external dependency, unresolvable ambiguity). Those *should* reach a human — that is the case HITL exists for. The design narrows HITL to that case, it does not abolish it.
- **Cost shifts from human-time to compute (bounded).** A decomposed issue spawns N child pipelines — more $ than a ~zero-compute human page. The depth cap + unchanged retry caps bound it (moderate appetite); a change that would fragment endlessly hits the depth cap and pages a human instead of burning.
- **Recursion must be capped.** No depth cap exists today; `max_decomposition_depth` is load-bearing against infinite fragmentation (a stalled child that keeps splitting into clones eventually hits the cap → HITL).
- **Scope is phased.** P1 inserts decompose before the auto-agent's terminal (main pipeline: plan/implement/review). P2 routes the ~7 side loops that file `hitl-escalation` directly (discover, contract-refresh, corpus-learning, …) through the same decompose-first terminal, so routine escalation is eliminated everywhere. (No parked-revisit phase — the floor is the existing HITL terminal.)
- **State reconciliation.** A stuck issue owns a branch/worktree/PR + attempt counters; on decompose, the terminal closes/cleans all of it, reusing the intake path's proven close-and-supersede handling.
