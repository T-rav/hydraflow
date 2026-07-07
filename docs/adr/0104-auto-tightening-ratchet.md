# ADR-0104: Auto-tightening ratchet

**Status:** Accepted
**Date:** 2026-07-05
**Enforcement:** enforced
**Enforced by:** pytest:tests/test_auto_tighten_invariant.py

## Context

ADR-0100 gave HydraFlow a measured conformance contract, and ADR-0093 gave loops a fitness scorecard, but a 2026-07-05 verification of both established that the system is **self-maintaining, not self-improving**. The ratchet never silently regresses, but every advance is a human commit: the P10.3 baseline, the coverage floor, the ADR grandfather set, the disturbance baselines are all raised by hand. `AdrConformanceLoop` only files issues, it never edits files. `FitnessScorecardLoop` is read-only by design, with "no optimizer, no climbing" as an explicit non-goal.

The gap to genuine self-improvement, in the one direction that is provably safe, is a loop that closes the ratchet on itself: when a gain is real and stable, lock it in automatically instead of waiting on a human chore. The safe direction is narrow and must stay narrow: **monotone-tighten only**. A mechanism that can raise a floor can be trusted with autonomy in a way a mechanism that can also lower one cannot, because raising a bar can never hide a regression and lowering one always can. This ADR is scoped to that one safe increment, not to self-improvement in general.

## Decision

### Generic engine, one lead adapter

A single `TighteningEngine` (pure orchestration, no I/O) sits behind a `RatchetAdapter` protocol so the same engine serves any monotonic baseline: a scalar (coverage), a per-signature count map (disturbance), or a set (allowlists). Each adapter supplies `current()`, `baseline()`, a strict `is_tighter(a, b)` predicate, a `weakest` fold across a window, and `apply_margin` to absorb measurement jitter. A landscape inventory of six human-advanced, computable, non-dampener baselines justified building the generic engine rather than a one-off script.

**Phase-1 lead adapter: the coverage floor** (`--cov-fail-under` in `pyproject.toml`). It is a scalar, "higher is tighter," owned by no other loop, and gains incidentally from nearly every test-adding PR, making it the simplest and highest-volume case to prove the engine on. The allowlist family (the ADR grandfather set, the telemetry-bypass allowlist) is a follow-on once each frozenset literal is extracted to a data file that machine edits can touch safely.

### Actuation and the confirmation gate

The dedicated caretaker loop, `AutoTightenLoop` (ADR-0029 shape: `enabled_cb`, config flag, kill-switch, off by default), asks the engine every tick to evaluate each registered ratchet and acts only on confirmed tightenings. Its entire write surface is opening a bot PR to `staging` with auto-merge, via the same `open_automated_pr_async` path other autonomous PR-authoring loops use. No direct file edits outside a PR branch, no issues filed.

A candidate gain is only actuated once **both halves** of a confidence gate hold:

- **Stability window.** The engine folds `weakest` across the trailing N observations (default 3 ticks) to get the loosest floor the whole window satisfied, then backs it off by a margin before comparing. A single flaky reading cannot lock in a value the code does not reliably hold, and the margin absorbs ordinary run-to-run coverage variance.
- **Attribution.** The gain must trace back to at least one merged PR or closed remediation issue that plausibly touches the relevant files, scanned back to baseline age. An unattributed improvement is held and flagged rather than tightened, since a measurement can be broken or gamed without a real code cause.

### The ADR-0046 answer for this loop

ADR-0046 asks who watches the watcher. For `AutoTightenLoop` the answer is structural, not procedural: every mutation this loop can make is provably monotone toward stricter gates, and every mutation is re-validated by the very gate it touches, because the tightening PR's own CI reruns the existing ratchet check against the new floor before merge. `TighteningEngine.guard_is_tighter` is a runtime guard that raises rather than actuate a non-tightening value, and a property test (`tests/test_auto_tighten_invariant.py`) proves no PR-authoring path is reachable with a value that is not strictly tighter than baseline. A watcher that can only make the rules harder to pass, and whose every rule-change must itself pass those harder rules, cannot degrade the system it watches. This closes ADR-0099's control-surface question for the tightening direction specifically, it does not address loosening, check generation, or config optimization, which remain out of scope (see Non-goals).

### The ADR-0101 boundary

ADR-0101's disturbance dampener and this loop both touch monotonic baselines, but they are not doing the same job and are not interchangeable. The dampener **fixes code** and prunes its own baseline in the same PR, so it is the primary mechanism for the disturbance dimension: it dispatches an agent to remove a violation and correct the baseline YAML in one commit. This loop never fixes code. It only **locks in gains that already exist**, whatever produced them. Because the dampener already prunes disturbance baselines as a side effect of fixing violations, a separate tightener there would be mostly redundant and would risk fighting the dampener over the same files. Disturbance is therefore demoted to a coordinated, build-only-if-needed adapter (a `DisturbanceAdapter` would have to defer to any open dampener PR on the same dimension, sharing its dedup namespace) rather than the Phase-1 lead. The coverage floor, which no other loop owns or prunes, took that role instead.

## Non-goals

No loosening of any baseline by any autonomous path; loosening stays human-gated (a `git revert` of a specific tightening PR). No fixing of code to produce a gain, that is ADR-0101's job. No check generation, no loop-config optimizer, no autonomous invention of new fitness functions; each is a separate future gap.

## Known pre-enable gates

`auto_tighten_loop_enabled` defaults to `False` and stays off until two gaps close, plus a canary phase:

1. **Cross-tick open-PR dedup probe.** Today a stuck or slow-to-merge tightening PR degrades to a benign hold because the actuation path runs with `raise_on_failure=False`; a dedicated dedup probe across ticks is needed before enabling so a stuck PR cannot silently mask a real regression on the next tick.
2. **Tier-C sandbox e2e** of the real PR-authoring chain (a sandboxed repo whose recorded coverage exceeds the floor by more than the margin, stable across the window, produces an actual `--cov-fail-under` bump PR that CI validates and merges).
3. **Phase-1 rollout runs in canary posture first**: bot PR with human merge, to observe real floor-raises before flipping auto-merge on.

## Consequences

The system gains one genuinely self-improving path that is safe by construction: gains that already exist stop waiting on a human chore to become durable. The generic engine means the second and third adapters (allowlists, and disturbance if ever needed) are additive, not a rewrite. The cost is a new caretaker loop, a new observation store (`.hydraflow/metrics/{repo_slug}/tighten.jsonl`), and the operational discipline of treating a false-wall tightening as a normal revertable PR rather than a special case. The monotone-tighten invariant is the one property this ADR is willing to enforce with a CI-blocking test; everything else (margin size, cadence, which adapters ship next) is tunable without touching the safety boundary.
