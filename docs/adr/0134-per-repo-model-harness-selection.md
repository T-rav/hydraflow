# ADR-0134: Per-repo model/harness selection — run Claude and GLM projects side by side

- **Status:** Accepted
- **Date:** 2026-08-14
- **Supersedes:** none
- **Superseded by:** none
- **Related:** [ADR-0110](0110-provider-harness-backend-split.md) (the provider/harness backend split this builds on), [ADR-0119](0119-credit-failover-to-glm.md) (the process-wide failover this composes with), [ADR-0009](0009-multi-repo-process-per-repo-model.md) (the per-repo `HydraFlowConfig` isolation this relies on)
- **Enforcement:** enforced
- **Binds:** both

**Enforced by:**
pytest:tests/test_repo_backend.py
pytest:tests/test_config_repo_provider.py
pytest:tests/test_base_runner_repo_provider.py
pytest:tests/test_base_subprocess_runner_repo_provider.py
pytest:tests/test_dashboard_routes_state.py

## Context

ADR-0110 split the provider (billing/endpoint) axis from the harness (CLI
tool) axis and gave every agentic role its own `*_provider` dial
(`implementation_provider`, `review_provider`, `planner_provider`,
`triage_provider`, `ac_provider`) plus a `maintenance_provider`/
`maintenance_model` knob that coherently routes the *maintenance* role-set
(wiki compilation, ADR review, transcript summary, ...) to GLM. ADR-0119 added
a controller that reroutes Claude *work* spawns to GLM on a credit cap. Both
prove the two-backend capability works in one process — but selection is
still **factory-wide**: every registered repo shares the same `*_provider`
defaults (env/config-file), and the individual per-role dials are
config-file/env-only — they were never added to `settings_registry.SETTINGS`,
so an operator could not even set them per-repo through the running system
(`PATCH /api/control/config?repo=X`, the Settings drawer) without dropping to
5 separate fields.

Issue #11211 asks for the natural next step: "I want to set model / harness
per project, not just a factory-wide default" — e.g. one repo running the
core factory pipeline on Claude while a second, concurrently-supervised repo
runs the same pipeline on GLM. Each registered repo already owns an
independent `HydraFlowConfig` instance (`repo_store.py`/`repo_runtime.py`,
ADR-0009's per-repo isolation) — the missing piece is a single per-repo dial
that governs the *work loop* role-set at spawn time, mirroring
`maintenance_provider`'s "one knob, coherent provider+model" pattern but for
implement/review/plan/triage instead of maintenance, and threaded through
the Settings-drawer-editable / `RepoRecord.overrides`-persisted seam every
other per-repo setting already uses.

## Decision

**Add a repo-wide `repo_provider`/`repo_model` dial, resolved at spawn time,
layered UNDER any explicit per-role dial and UNDER credit-failover.**

1. **Config** (`config.py`) — `repo_provider: Literal["claude", "zai"] =
   "claude"` and `repo_model: str = ""` (validated glm-* when non-empty,
   mirroring `credit_failover_model`). Registered in
   `settings_registry.SETTINGS` (`Model Routing` group) — the *only* step
   needed to make them Settings-drawer-editable and
   `PATCH /api/control/config?repo=X`-mutable, since the route derives its
   allowlist from `set(SETTINGS)`. Persisted exactly like every other
   per-repo setting, via `RepoRecord.overrides` → `valid_stored_overrides` →
   `load_runtime_config(overrides=...)` — no new persistence mechanism.

2. **Spawn routing** (`repo_backend.apply_repo_provider`) — a new function
   mirroring `apply_credit_failover`'s exact contract: no-op unless the
   provider handed to it is still `"claude"` (an explicit per-role dial that
   already routed a spawn off Claude always wins) AND `config.repo_provider
   == "zai"` AND a `ZAI_API_KEY` is present (never reroute to an endpoint
   with no key — that would send a glm-* model to the wrong backend).
   Rewrites `--model` to `repo_model` (or `credit_failover_model` as a
   fallback when `repo_model` is unset). Applied at the SAME two seams
   credit-failover already reroutes, immediately BEFORE it:
   `base_runner._execute` and `BaseSubprocessRunner.run`. Combined resolution
   order at each seam:

   ```
   role dial (explicit non-claude *_provider) > repo_provider > credit-failover
   ```

   Because `BaseSubprocessRunner`-based runners (e.g. the ADR-0050 Auto-Agent
   preflight loop) have no role-level provider dial of their own — they
   always spawn on native Claude — `repo_provider` is the *only* lever that
   routes their spawns to GLM, closing the gap ADR-0119 left in that seam
   (it only reroutes there under credit exhaustion, never under a standing
   per-repo choice).

3. **Concurrency** — no new plumbing. Each `RepoRuntime` already owns an
   independent `HydraFlowConfig`, event bus, and orchestrator (its own
   runner pools), so two repos on different `repo_provider` values already
   run concurrently by construction (ADR-0009). Credit-exhaustion pause
   isolation (#9807) is already per-orchestrator-instance-scoped *across
   repos* — one repo's Claude cap never pauses a different repo's loops. The
   one genuinely process-wide piece is `credit_failover`'s engage flag
   (ADR-0119, §Consequences: "one shared Claude subscription") — it composes
   correctly with no code change: `apply_repo_provider` runs first and, once
   it has already routed a repo's spawn to `"zai"`, `apply_credit_failover`'s
   own `provider != "claude"` guard is a no-op. A GLM-native repo is
   therefore immune to a Claude-cap failover engaged by a different,
   Claude-native repo sharing the process; a repo left on the factory
   default still fails over, unchanged from pre-#11211 behavior. Verified in
   `tests/test_repo_backend.py` (composition, through the real
   `apply_repo_provider`/`apply_credit_failover` seam functions) and
   `tests/scenarios/test_multi_repo_backend_routing.py` (two repos, two
   backends, live simultaneously; a sibling's engaged failover doesn't move
   the GLM-native repo's resolved provider or model). **Not covered:**
   *within* a single GLM-pinned repo's own orchestrator, the #9807
   pause-classifier (`orchestrator._loop_providers`) has no knowledge of
   `repo_provider` — see the Known gap below.

4. **Cost attribution** — no new plumbing. The rerouted `cmd` (with its
   rewritten `--model`) flows unchanged into `parse_command_tool_model` and
   `PromptTelemetry.record`, exactly as credit-failover's reroute already
   does — the z.ai cost double-count fix and per-repo cost rollups
   (`dashboard_routes/_cost_rollups.py`, `_cost_merge.py`) attribute
   correctly for free.

5. **UI** — `RepoRuntimeInfo.provider` (new field, sourced from
   `_state_routes._effective_repo_provider`) surfaces the resolved backend —
   not just the configured dial — to `GET /api/runtimes`/
   `GET /api/runtimes/{slug}`: `repo_provider == "zai"` with no
   `ZAI_API_KEY` present resolves to `"claude"` (mirroring
   `apply_repo_provider`'s own fail-safe), so the badge never claims GLM for
   a repo whose spawns are silently staying on Claude. `RepoOverview.jsx`
   badges a non-default repo (`"GLM"`) in the multi-repo portfolio row. The
   Settings drawer needs no bespoke component — `repo_provider`/`repo_model`
   render generically like every other `SETTINGS` entry, in the same "Model
   Routing" group as `zai_base_url`. `ZAI_API_KEY` presence is already
   surfaced generically by `GET /api/control/settings-schema`'s
   `provider_keys` (keyed by the same `"zai"` backend credit-failover and
   ADR-0110 already use) — no new key-presence plumbing needed.

## Consequences

- **A repo's backend choice is a single dial**, not five separate `*_provider`
  fields — an operator sets `repo_provider=zai` (+ `repo_model`) once per
  repo and every `BaseRunner`-based work-loop role (implement/review/plan/
  triage) and every `BaseSubprocessRunner`-based spawn for that repo routes
  to GLM.
- **An explicit per-role dial still wins.** `repo_provider` only acts on a
  spawn still resolving to `"claude"`; a repo that wants e.g. `triage` alone
  routed differently sets `triage_provider` directly and it is untouched by
  `repo_provider`.
- **Maintenance loops are untouched** — `maintenance_provider` dials that
  role-set independently, same as it does today under ADR-0119.
- **Known gap: direct `stream_claude_with_telemetry` callers are NOT
  covered.** `repo_provider` is wired at the same two seams
  `apply_credit_failover` uses (`base_runner._execute`,
  `BaseSubprocessRunner.run`) — mirroring ADR-0119's identical scope, not a
  regression from it. Roles that spawn directly through
  `runner_utils.stream_claude_with_telemetry` bypass both seams and stay on
  their own `*_provider` dial regardless of `repo_provider`: the AC
  generator (`acceptance_criteria.py`, `ac_provider`), the verification
  judge (`verification_judge.py`, `review_provider`), and `report_issue`
  (`report_issue_loop.py`, hardcoded `"claude"`). A repo set to
  `repo_provider=zai` with these dials left at their `"claude"` default
  still spawns AC generation, AC precheck, the verification judge, and
  report-issue on native Claude. Fixing this belongs at the call sites (an
  explicit `ac_provider`/`review_provider` override, or a future per-role
  fallback to `repo_provider`), not inside the shared seam — blanket-wiring
  `stream_claude_with_telemetry` would also reroute `report_issue`, which is
  maintenance-class and must stay untouched per the bullet above. Tracked
  as a follow-up (#11235); not yet enforced by this ADR's test list.
- **Known gap: the #9807 credit-pause classifier does not consult
  `repo_provider`.** `orchestrator._loop_providers` maps only the
  *maintenance* loop names to their own `*_provider` dial via
  `_BACKEND_WORKER_LOOPS`; every other loop — including the four work loops
  `repo_provider` routes (`implement`/`review`/`plan`/`triage`) — always
  classifies as `PROVIDER_ANTHROPIC` for pause-scoping, regardless of
  `repo_provider`. Combined with the gap above (ac/judge/report_issue still
  spawning on native Claude for a GLM-pinned repo), an Anthropic cap raised
  by one of those still-Claude seams pauses that *same* repo's own
  `implement`/`review`/`plan`/`triage` loops and terminates its harness
  runner pools — even though those loops' own spawns already route to GLM.
  This does not contradict the Concurrency section's isolation claim (that
  claim is about one repo's pause never reaching a *different* repo's
  loops, which still holds); it is a distinct, intra-repo classification gap
  the pause-scoping code predates #11211 for the existing per-role
  `*_provider` dials and this ADR does not close. Tracked as a follow-up
  (#11238); not yet enforced by this ADR's test list.
- **The `credit_failover` process-wide engage flag is unchanged** and still
  a known, documented limitation (ADR-0119 §Consequences: "one shared Claude
  subscription"). This ADR does not scope it per-repo; a GLM-native repo is
  already immune by construction (it never presents a `"claude"` provider to
  `apply_credit_failover`), and a Claude-native repo sharing the process
  correctly still shares the process's Claude-cap fate.
- **Requires `ZAI_API_KEY`**, exactly like credit-failover — without it,
  `repo_provider=zai` is configured but inert (spawns silently stay on
  Claude), matching the "fail open to the safe backend, never mid-spawn"
  precedent ADR-0119 established.
