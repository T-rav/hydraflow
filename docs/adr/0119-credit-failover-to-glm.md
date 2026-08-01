# ADR-0119: Credit failover — reroute work to GLM instead of pausing when Claude credits are exhausted

- **Status:** Accepted
- **Date:** 2026-08-01
- **Supersedes:** none
- **Superseded by:** none
- **Related:** [ADR-0110](0110-provider-harness-backend-split.md) (the provider/harness backend split this builds on), [ADR-0029](0029-caretaker-loop-pattern.md) (loops are reflexes)
- **Enforcement:** enforced
- **Binds:** both

**Enforced by:**
pytest:tests/test_credit_failover.py

## Context

When Claude subscription credits are exhausted the factory **stops**. `CreditExhaustedError` is raised per-spawn and the orchestrator's `_pause_for_credits` pauses the affected loops until the parsed reset time. The multi-backend capability exists — ADR-0110 split provider (billing/endpoint) from harness (CLI tool), and `maintenance_provider="zai"` already routes maintenance loops to GLM — but provider selection is a **static config dial**, not a controller that observes credit state and re-routes work.

So the situation issue #10844 (P0) named: the capability to run on another backend exists; the controller that would use it on saturation does not. A Claude cap on ~2026-07-27/28 lost ~two days of capacity because nothing failed the *work* loops over to the GLM backend that was sitting right there. ADR-0110 explicitly deferred "routing a top-level agentic work loop to z.ai" as a follow-up. This ADR is that follow-up.

## Decision

**On an authoritative Claude credit cap, reroute work spawns to the z.ai GLM backend and keep working, instead of pausing. Auto-probe Claude after a cooldown; the first successful probe switches work back.**

1. **Runtime failover state** (`src/credit_failover.py`) — an in-memory module singleton is the single owner of whether work spawns are currently rerouted to GLM. `engage` sets it (scheduling the first Claude probe at the error's reset time, or a cooldown); `clear` unsets it; `is_active()` is read at spawn time. In-memory by design: on a restart mid-failover the first Claude spawn simply re-caps and re-engages — one bounded wasted spawn, not a correctness bug.

2. **Spawn rerouting** (`base_runner._execute`) — `apply_credit_failover(provider, cmd, config)` reroutes a would-be `claude` work spawn to `zai` and rewrites its `--model` to `credit_failover_model` (`glm-5.2`) **only** when failover is active, `credit_failover_enabled`, and a `ZAI_API_KEY` is present. It flows unchanged through `resolve_harness_env` into the per-spawn env (ADR-0110, never global). The rerouted `cmd` reaches telemetry too, so cost attributes to the GLM model.

3. **Engage** (`orchestrator._maybe_engage_failover`) — a short-circuit at the top of `_handle_credit_exhaustion`: an **authoritative** cap tagged `anthropic`/`claude`, with the feature enabled and a `ZAI_API_KEY`, engages failover and restarts the crashed loop now (it re-runs routed to GLM). Everything else — prose-only signals needing corroboration, non-Claude (zai/kimi) caps, no key, feature disabled — falls through to the **unchanged** `_pause_for_credits` logic. A GLM cap while already failed over (`provider="zai"`) therefore pauses normally: both backends down.

4. **Switch-back** (`orchestrator._probe_claude_for_switchback`, run by a probe task) — once the scheduled `probe_after` arrives, a cheap Claude availability probe runs; success clears failover so work routes back to Claude, failure pushes the next probe out by a cooldown. A probe cannot detect a *weekly* cap (the key stays valid), so a cleared failover is provisional: the next real Claude spawn is the true arbiter, and if it re-caps, failover re-engages with the fresh reset time. The probe is re-armed on orchestrator **startup** whenever failover is already active (`_rearm_failover_probe_if_active`) — without that, a stop/start while failed over would leave work silently pinned to GLM, because every spawn reroutes before it can raise the fresh cap that would otherwise re-arm the probe.

Because `apply_credit_failover` guards every work-spawn path (`base_runner._execute` and `BaseSubprocessRunner.run`), an authoritative Claude cap fails a loop over *and its restart succeeds on GLM*; the engage short-circuit's "restart the crashed loop now" is therefore safe for every reroutable work loop rather than converting a clean pause into a crash-loop.

Config: `credit_failover_enabled` (default **on**, env `HYDRAFLOW_CREDIT_FAILOVER_ENABLED`), `credit_failover_model` (`glm-5.2`, validated `glm-*`), `credit_failover_cooldown_minutes` (15).

## Consequences

- **The factory keeps working through a Claude cap** instead of losing capacity, at GLM quality/cost for the duration. This is the intended trade: continued throughput over idle waiting.
- **Failover requires `ZAI_API_KEY`.** Without it, `resolve_harness_env` would silently fall back to Claude, so the engage path refuses to fire and the existing pause behavior is preserved — a safe, explicit precondition, not a silent no-op mid-spawn.
- **Maintenance loops are untouched** — they dial their backend independently (`maintenance_provider`). Failover is scoped to the Claude *work* loops.
- **Bounded flap during a weekly cap:** because the probe can't see weekly exhaustion, a cleared-then-re-capped cycle wastes at most one Claude work spawn per cooldown (15 min). Longer cooldowns trade recovery latency for fewer wasted spawns.
- **No persistence (v1).** The failover flag is a process-global that survives an in-process stop/start (so `_rearm_failover_probe_if_active` re-arms the probe on start), but not a full process restart. A fresh process re-engages on the first cap. Cross-restart persistence is a possible follow-up.
- **Multi-repo probe ownership.** The failover flag is process-global (one shared Claude subscription) but the probe task is per-orchestrator. Each orchestrator arms a probe on startup and on observing a cap while already failed over, so any repo that (re)starts or re-caps guarantees a live probe. The narrow residual: if the sole probe-owning orchestrator stops while other repos keep running and never re-cap (their spawns already route to GLM), switch-back stalls until some orchestrator restarts. A process-global probe would close this fully and is a candidate follow-up.
- **The credit-pause path is unchanged for everything that is not a clean Claude cap** — the short-circuit is additive and guarded, and the full existing credit-pause test suite stays green.
