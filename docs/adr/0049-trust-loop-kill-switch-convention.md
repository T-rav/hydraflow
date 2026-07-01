# ADR-0049: Trust-loop kill-switch convention (`enabled_cb` only, no config-only)

- **Status:** Accepted
- **Date:** 2026-04-23
- **Accepted:** 2026-05-30
- **Supersedes:** none
- **Superseded by:** none
- **Related:** [ADR-0045](0045-trust-architecture-hardening.md) §12.2 (spec reference); [ADR-0048](0048-auto-revert-on-rc-red.md) (relies on live kill for StagingBisectLoop).

**Enforcement:** enforced

**Enforced by:**
pytest:tests/test_loop_kill_switch_completeness.py
pytest:tests/regressions/test_canonical_killswitch.py

## Context

Every autonomous loop in HydraFlow needs an off switch for the same reason every engine needs an emergency brake: when a loop misbehaves in production — opens runaway PRs, floods issues, pegs CPU — the operator needs a **live** stop without editing config, rebuilding, or restarting the process. In the initial trust-fleet design some loops used a config field (e.g. `staging_enabled`) as their gate, which made the only way to stop them a config edit + orchestrator restart. That's catastrophic for dark-factory: a misbehaving loop can cause damage in the 30-60 seconds a restart takes, and some environments can't restart quickly.

We saw this concretely during the dark-factory review of PR #8390: `StagingBisectLoop._do_work` was gating on `self._config.staging_enabled`. Since that loop opens auto-revert PRs — the single highest-autonomy action in the fleet — the gap meant operators had no live brake for the most dangerous loop. A single config-only toggle for a dangerous loop is an anti-pattern.

We needed one convention, applied consistently across the fleet, that makes the live UI kill-switch both necessary and sufficient to stop any loop.

## Decision

**Every `BaseBackgroundLoop` subclass must gate `_do_work` on `self._enabled_cb(self._worker_name)` at the top of the method and return `{"status": "disabled"}` when the callback returns `False`.**

```python
async def _do_work(self) -> dict[str, Any] | None:
    if not self._enabled_cb(self._worker_name):
        return {"status": "disabled"}
    # ... rest of the tick
```

The `enabled_cb` is wired by `LoopDeps` to the System-tab worker-enable state (`BGWorkerManager.is_enabled`). The dashboard's toggle writes this state persistently; the change is observable within one loop tick.

### Rules

1. **No `*_enabled` config field as the sole gate.** A config field may exist for dark-launch purposes (e.g. `staging_enabled` to keep a loop behind a feature flag until its scaffolding is proven), but it must be an **AND** with `enabled_cb`, not a replacement. The `enabled_cb` check comes FIRST.
2. **The check is in-body, not only in the base class.** The base class's `run()` method does check `enabled_cb` before each tick, but that relies on the scheduler firing normally. An explicit in-body check makes the behavior visible in tests that invoke `_do_work` directly, and preserves the guarantee if a future refactor changes the scheduler.
3. **The return value is `{"status": "disabled"}`.** Consistent return value across the fleet makes it easy to assert in tests and to aggregate in `TrustFleetSanityLoop` metrics.
4. **No exceptions to this convention.** Even loops that "can't really misbehave" follow it — the convention is uniform so operators don't have to remember which loops respond to the toggle.

## Consequences

**Positive:**
- Operators have one place to stop any loop — the System tab. This is the same place they manage intervals and see heartbeats, so the mental model is unified.
- Tests that pass `enabled_cb=lambda _: False` can deterministically short-circuit any loop without mocking subprocess calls or seeding state.
- A misbehaving loop costs ~1 tick interval (usually seconds to minutes) to stop, not a restart.
- Code review has a one-line thing to look for in every new loop: `if not self._enabled_cb(self._worker_name):`.

**Negative:**
- A compromised or buggy `BGWorkerManager` could disable all loops with one call. Mitigated by the manager being a single small class with high test coverage and no runtime-mutable dependencies.
- The `enabled_cb` is a sync callable on an async method — a future refactor to an async callable would touch every loop. Acceptable because today's sync signature matches the dashboard's simple state read.

**Neutral:**
- Dark-launch flags (like `staging_enabled`) remain useful for rolling out a loop to production incrementally. They just can't be the only stop button.

## Verifying compliance

`tests/test_loop_kill_switch_completeness.py` is the hard CI gate: it AST-discovers every `BaseBackgroundLoop` subclass in `src/*_loop.py` and fails closed if any `_do_work` omits the `self._enabled_cb(self._worker_name)` gate, with an empty grandfather list so the gap cannot silently reopen. For a quick manual spot-check, `grep -l "async def _do_work" src/*_loop.py | xargs grep -L "self._enabled_cb"` lists any violators.

(The original convention deliberately stopped at a code-review grep "not a hard CI gate" so as not to dictate the exact line of the check. The kill-switch-integrity work — see Update Log — replaced that stance with the completeness ratchet above, which asserts presence of the gate without dictating its exact placement.)

The dark-factory review agent dispatched for any PR >500 lines touching `src/*_loop.py` should also flag violations as blockers.

## When to supersede this ADR

- If the factory grows loops with such different urgency profiles that one System-tab toggle isn't sufficient (e.g. some loops need a "pause" vs "drain" vs "stop" distinction), propose a new kill-switch model.
- If `BGWorkerManager` is replaced by a different state layer, update this ADR's reference.

## Related

- `src/base_background_loop.py::LoopDeps` — the dataclass that carries `enabled_cb` to each loop.
- `src/bg_worker_manager.py::BGWorkerManager.is_enabled` — the backing implementation.
- `src/ui/src/constants.js::EDITABLE_INTERVAL_WORKERS` — the list of loops the System tab exposes for toggling.
- `tests/test_*_loop.py` — test fixtures that stub `enabled_cb` to exercise the disabled branch.

## Update Log

- **2026-05-30: Promoted Proposed → Accepted.** The convention shipped fleet-wide and is now hard-enforced. The kill-switch-integrity work fixed the `DiagramLoop` `worker_name` hyphen/underscore mismatch, added the in-body `_enabled_cb` gate to the four env-only loops (`cost_budget_watcher`, `diagram`, `entry_evidence`, `pricing_refresh`), and landed `tests/test_loop_kill_switch_completeness.py` — an AST-discovery ratchet with an empty grandfather list that fails CI if any `BaseBackgroundLoop` subclass omits the gate. This supersedes the original "simple grep in code review, not a hard CI gate" enforcement stance recorded above under *Verifying compliance*: the gate is now a CI hard-stop, so the decision is no longer aspirational.
