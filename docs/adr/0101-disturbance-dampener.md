# ADR-0101: Disturbance Dampener — feedforward ratchet + burn-down loop

**Status:** Proposed
**Date:** 2026-07-01
**Enforced by:** tests/test_disturbance_ratchet.py, tests/test_disturbance_dampener_loop.py

## Context

ADR-0099 models HydraFlow's orchestration layer as a hierarchy of control loops and names, without deciding, a set of known-open control surfaces. §6 surface #3 is:

> **Disturbance rejection is reactive, not feedforward** — no generalized "snapshot baseline → block new → burn down" control component.

Concretely: quality regressions that are cheap to introduce one file at a time — an untyped `Mock()` that grows undeclared attributes, a blanket `# type: ignore` / `# noqa` suppression — currently have no dedicated rejection mechanism. Existing gates (ruff, pyright, bandit, the mock-spec AST detector retired in `9dcb70a9`) either catch a violation the moment it's introduced (a hard block that can't distinguish "this PR added one more of these" from "this repo has always had a pile of these") or catch nothing at all once a suppression is already in place, because a single blanket suppression silently permits an unbounded number of future violations under the same signature. Neither shape gives a lights-off pipeline a way to (a) stop the backlog from growing while (b) not requiring an all-at-once big-bang fix to adopt the gate, and (c) actually drain the existing backlog over time without a human queuing up cleanup work file by file.

This is a disturbance-rejection problem in the ADR-0099 sense: the "clean codebase" set-point is being pushed off by an ongoing stream of small disturbances (each new suppression, each new untyped mock), and the existing gates are pure feedback (react to what's already landed) with no feedforward component that (1) fixes a baseline reference point, (2) blocks the disturbance from growing past it, and (3) actively drives the measured value back down toward zero over time.

## Decision

Introduce the **Disturbance Dampener**, a three-part control component realizing feedforward disturbance rejection + burn-down for count-per-signature quality dimensions. It generalizes across dimensions; two are wired in at launch: `mock_spec` (untyped `Mock()`/`MagicMock()` usage detected via `src/_mock_spec_detector.py`, adapted by `src/disturbance/detectors/mock_spec.py:MockSpecDetector`) and `suppressions` (`# type: ignore` / `# noqa` occurrences, `src/disturbance/detectors/suppressions.py:SuppressionsDetector`). Each dimension is declared once in `src/disturbance/registry.py:DIMENSIONS` as a `DimensionSpec` binding a detector, a version-controlled baseline path (`disturbance/baselines/<dimension>.yaml`), and a fix prompt.

**1. Sensor — the `ViolationDetector` protocol.** `src/disturbance/detectors/base.py:ViolationDetector` is a pluggable, pure protocol: `detect(repo_root) -> list[Finding]`, reads files only, no side effects. Each `Finding` carries a `signature` — a stable per-occurrence identity (e.g. `path::mock_spec` or the specific noqa/ignore code) — so occurrences can be counted and diffed per signature rather than treated as an undifferentiated total.

**2. Governor — the count-per-signature baseline ratchet gate.** `src/disturbance/baseline.py` snapshots current findings into a version-controlled YAML baseline (`save_baseline`) and `diff()`s a fresh detector pass against it, bucketing every signature into `new` (blocks the PR — the feedforward rejection), `resolved` (burn-down progress), or `unchanged` (still present, not growing). `src/disturbance/gate.py:run_gate` runs this per dimension and is the CI-time enforcement point: a PR that introduces a *new* violation under any tracked signature fails; a PR that only touches already-baselined signatures does not, because retrofitting a hard block onto an existing backlog with no adoption path would be a stop-the-world migration, not a control loop. This is the "block new" half of ADR-0099 surface #3.

**3. Actuator — `DisturbanceDampenerLoop` (Pattern A, per-file agent dispatch).** `src/disturbance_dampener_loop.py:DisturbanceDampenerLoop` is the burn-down half. Each tick it: runs every dimension's detector, loads its baseline, and calls `src/disturbance/burndown.py:select_units` to pick a capped, smallest-first, deduped batch of `BurndownUnit`s (one per dimension+file). For each unit it dispatches a coding agent (`self._runner`) with a generated fix prompt via `generate_and_open_pr_async` (`src/auto_pr.py`), instructing the agent to both fix the violations in that file *and* prune the corresponding entries from the dimension's baseline YAML — the loop is self-verifying: if the agent fixes the code but doesn't touch the baseline, the next gate run reports the signature as `resolved` and the stale baseline entry is corrected; if the agent prunes the baseline without actually fixing the code, `run_gate` sees the signature reappear as `new` and blocks the PR. One PR is opened per file, labeled `disturbance-dampener`, targeting `self._config.base_branch()`. It follows `SandboxFailureFixerLoop`'s established runner/attempt-cap/kill-switch shape: `LoopDeps`-based caretaker wiring, `disturbance_dampener_max_prs_per_tick` bounding the actuator's saturation, per-unit attempt counters (`get/bump_disturbance_dampener_attempts`) capped at `auto_agent_max_attempts`, dedup via `self._dedup` so a unit already turned into an open PR isn't redispatched, and `reraise_on_credit_or_bug` in its per-unit exception handler so a billing-exhaustion signal isn't silently absorbed as a per-file failure.

Together the three parts close the loop ADR-0099 left open: the Sensor measures the disturbance, the Governor's baseline gate fixes a reference point and blocks growth past it (feedforward), and the Actuator drives the measured value back toward the zero set-point over successive ticks (burn-down) — without requiring the backlog to be cleared in one pass before the gate can be turned on.

## Consequences

- New violations under a tracked dimension are rejected at PR time from the moment a dimension's baseline is first snapshotted, regardless of how large the pre-existing backlog is — the adoption cost is one baseline snapshot per dimension, not a mass cleanup.
- The backlog trends toward zero autonomously: each tick opens up to `disturbance_dampener_max_prs_per_tick` fix PRs without a human queuing cleanup work, consistent with the dark-factory operating contract.
- Adding a new disturbance dimension is a one-line addition to `DIMENSIONS` (detector + baseline path + fix prompt) — the loop, gate, and burn-down selection are dimension-agnostic.
- The loop is a coding-agent actuator: each unit costs one agent dispatch (`LONG_LLM_CYCLE = True`, longer watchdog), so burn-down throughput is bounded by `disturbance_dampener_max_prs_per_tick` and by credit/attempt budgets, not by backlog size — a large backlog burns down gradually across many ticks rather than all at once.
- A fix PR that only prunes the baseline without truly fixing the violation is self-correcting at the *next* gate run (the pruned signature reappears as `new` and blocks), but is not caught synchronously within the same PR unless the ratchet gate itself runs in that PR's CI — this is the expected shape (the gate is what's Enforced by, not the loop's own judgment of its fix).
- Two independent dimensions (`mock_spec`, `suppressions`) share one mechanism instead of two bespoke gates; the previous bespoke mock-spec gate was retired (`9dcb70a9`) in favor of this generalized adapter.

## Alternatives considered

- **Pattern B — file issues instead of opening PRs directly.** Rejected. The talk's framing for this control surface is direct feedforward correction: the actuator should act on the plant (open a fix PR), not defer action to a second, separately-triggered pipeline stage (file an issue, wait for it to be picked up, then dispatch a fix). Filing issues would reintroduce a human/queue-mediated hop that the dark-factory operating contract exists to remove for tractable, reversible, bounded-blast-radius work — burning down a single file's lint/mock-spec debt is exactly that. Pattern A (direct PR per unit) keeps the loop closed within the caretaker fleet itself.
- **Fix the entire backlog in one PR per dimension.** Rejected. A single all-file PR per dimension would be large, slow to review, and would forfeit the incremental, capped, per-tick shape every other caretaker loop in the fleet uses (ADR-0029); per-file units also make `select_units`' smallest-first ordering and per-unit attempt caps meaningful.
- **Hard-block all pre-existing violations immediately (no baseline).** Rejected. This would make adopting the gate on an existing dimension a stop-the-world migration blocking all unrelated PRs until the backlog was manually cleared first — infeasible for a repo with a real backlog and precisely the reactive-only failure mode this ADR exists to fix.

## Related

- ADR-0099 (orchestration as a control system — this realizes known-open surface #3, feedforward disturbance rejection + burn-down)
- ADR-0029 (caretaker loop pattern — `DisturbanceDampenerLoop`'s runner/attempt-cap/kill-switch shape)
- ADR-0049 (kill-switch convention — the loop's governor interlock)
- ADR-0082 (declarative gate contract — `run_gate`'s shape as a CI-time gate)
- ADR-0021 (persistence architecture and data layout — the version-controlled YAML baseline files and per-unit attempt-counter state)
