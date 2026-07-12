# ADR-0105: Autonomous Convergence via Decomposition

- **Status:** Proposed
- **Date:** 2026-07-12
- **Supersedes:** none
- **Superseded by:** none
- **Amends:** [ADR-0084](0084-auto-agent-universal-root-cause-gate.md) (Auto-Agent as a Universal, Persistent, Root-Cause HITL Gate) — keeps its architecture and interception model, and replaces its terminal `human-required` hand-off with an autonomous decompose-or-park terminal.
- **Related:** [ADR-0002](0002-labels-as-state-machine.md) (label state machine); [ADR-0050](0050-auto-agent-hitl-preflight.md) (auto-agent pre-flight loop); [ADR-0029](0029-caretaker-loop-pattern.md) (caretaker loop pattern); [ADR-0044](0044-hydraflow-principles.md) (recursion safety); [ADR-0051](0051-iterative-production-readiness-review.md) (iterative review convergence).
- **Enforced by (planned):** `tests/test_issue_decomposer.py`; `tests/test_auto_agent_decompose_terminal.py`; `tests/test_decomposition_depth_cap.py`; `tests/scenarios/test_decompose_to_converge_scenario.py`; `tests/sandbox_scenarios/scenarios/s54_decompose_to_converge.py`.

## Context

[ADR-0084](0084-auto-agent-universal-root-cause-gate.md) made the Auto-Agent a universal gate that intercepts `hitl-escalation` issues, attempts an autonomous fix, and pages a human only for genuinely novel failures. Its terminal, when the auto-agent's own budget (`auto_agent_max_attempts`, default 3) is spent, is to stamp **`human-required`** (`auto_agent_preflight_loop.py:180`, `preflight/decision.py:96`) — a human-owned state.

The operating requirement has tightened: **no change may terminate at a human.** Every change must reach an autonomous terminal state. A human endpoint is unacceptable because it blocks the dark factory on operator availability and defeats "intent in, software out."

But "no human" and "no unbounded burn" cannot both be absolute. Some changes are genuinely unwinnable *as posed* — too broad, ambiguous, or blocked on an external unknown. The lever HydraFlow already has for "too big to converge as one unit" is **decomposition**: `Triage.run_decomposition` already splits an issue into an epic + 2–6 child specs, and `EpicCompletionChecker`/`EpicSweeperLoop` already auto-close a parent when its children merge. Today that path fires only on **intake complexity**, never on **retry exhaustion**.

## Decision

When a change exhausts the auto-agent's budget, **decompose it into smaller child issues instead of paging a human**. The parent converges when its children converge. This amends ADR-0084's terminal; the interception model, retry semantics, and playbooks are unchanged.

1. **Redirect the terminal.** At the two `human-required` sites, route instead to a decompose step. `human-required` is no longer applied by the main pipeline.

2. **Stall-aware decomposition.** Extract `Triage.run_decomposition` + `TriagePhase._maybe_decompose` into a standalone `IssueDecomposer` service callable from the auto-agent. The auto-agent invokes it with **stall context** (the failing stage, `blocked_reason`, diagnosis, diff-so-far, review findings) and a stall-aware prompt: "this change failed to converge because X — split it into smaller, independently-shippable slices, each with tight acceptance criteria." This is distinct from the intake-complexity prompt.

3. **Reuse the epic machinery.** On `should_decompose = true`: create the epic + children (children enter at `hydraflow-find` and run the full pipeline), `register_epic(auto_decomposed=True)`, then close the stuck issue as `decomposed`, close its superseded PR, and let `workspace_gc_loop` reap its worktree — the exact terminal pattern intake decomposition already uses. Parent rollup is free (`EpicCompletionChecker` + `EpicSweeperLoop`).

4. **Bounded depth (moderate budget).** A new `max_decomposition_depth` (default 2) caps recursion: a decomposed child that also stalls may split once more, then hits the floor. Depth is tracked per epic/child. The pre-decompose retry caps (implement 3 / review 2 / auto-agent 3) are unchanged — they are the "fair shot" before a split.

5. **The floor: auto-park, never a human.** When `should_decompose = false` (not decomposable) OR depth is exhausted, the terminal is **`parked`** + a full diagnostic comment — never `human-required`. Parked issues are revisitable (a periodic loop re-attempts them on new staging state / freed budget) but never block on an operator and never burn unbounded. "Converge" therefore includes "parked-with-diagnostic" for the residual set that is neither mergeable nor decomposable.

## Consequences

- **Zero human terminal for the main pipeline.** No pipeline change reaches `human-required`; it reaches merged, decomposed→merged, or parked.
- **Honest limit.** Decomposition turns *too-big / ambiguous* into *tractable*; it cannot manufacture a merge for a genuinely-impossible change. Those park with a diagnostic. This is the accepted trade of "no human" against "not every change becomes a merge."
- **Cost shifts from human-time to compute.** A decomposed issue spawns N child pipelines — more $ than a ~zero-compute human page. The depth cap + unchanged retry caps bound it (moderate appetite).
- **Recursion must be capped.** No depth cap exists today; `max_decomposition_depth` is load-bearing against infinite fragmentation.
- **Scope is phased.** P1 covers the main pipeline (plan/implement/review → auto-agent). P2 routes the ~7 side loops that file `hitl-escalation` directly (discover, contract-refresh, corpus-learning, …) through the same terminal. P3 adds the parked-revisit loop. Full zero-HITL is reached at P2; P1 alone still leaves side-lane human pages.
- **State reconciliation.** A stuck issue owns a branch/worktree/PR + attempt counters; the decompose terminal closes/cleans all of it, reusing the intake path's proven close-and-supersede handling.
