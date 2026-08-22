# ADR-0141: Bounded, reversible routing enforcement — the resolve-and-mint canary

**Status:** Accepted
**Date:** 2026-08-22
**Enforcement:** enforced
**Binds:** factory
**Supersedes:** none
**Superseded by:** none
**Related:** [ADR-0085](0085-secrets-never-persist-in-audit-stream.md) (the credential-absence guards the mint and its decision view are added to), [ADR-0110](0110-provider-harness-backend-split.md) (the provider/harness binding an account is compiled from), [ADR-0119](0119-credit-failover-to-glm.md) (a legacy mechanism that still decides the *input* route inside the canary), [ADR-0134](0134-per-repo-model-harness-selection.md) (the per-repo dial this neither reads nor retires), [ADR-0137](0137-fenced-issue-driver-and-director-runtime-boundary.md) (`src/driver_contracts.py:WorkerRole` and `ModelRequirement`, carried on the wire rather than re-declared), [ADR-0138](0138-gateway-account-identity-and-sanitized-route-visibility.md) (account identity, the sanitized route views this joins to, and §D5's dashboard write-boundary precondition), [ADR-0139](0139-shadow-routing-policy-resolver.md) (the resolver whose return this phase stops discarding), [ADR-0140](0140-revision-safe-policy-workspace-and-operator-write-boundary.md) (the write plane that authors the canary's one rule, and the before/after matrix its blast radius is computed from). Design source: `docs/proposals/gateway-routing-control-plane.md` §"P3 — resolve-and-mint canary". Issues: #11539 (this phase), #11531 (the epic), #11538 (the phase this builds on), #11540 / #11541 (the phases this unblocks).

**Enforced by:**
pytest:tests/test_route_enforcement.py
pytest:tests/test_route_mint.py
pytest:tests/test_governed_preflight.py
pytest:tests/test_gateway_secret_absence.py
pytest:tests/regressions/test_issue_11539_canary_off_is_byte_identical.py
pytest:tests/scenarios/test_gateway_enforcement_canary_scenario.py

**Precedent:** Canary releasing / progressive delivery — exposing a new decision path to a deliberately small, named slice of traffic with a one-move rollback (the canary-release pattern; Humble & Farley, *Continuous Delivery*; Sato's "CanaryRelease" bliki entry).
**Divergence:** a classic canary slices by *percentage of traffic* and rolls back by shifting that percentage, so the slice is a statistical property nobody can enumerate. Here the slice is enumerable by construction — one canonical `owner/repo` × the gateway transport — and the rollback is not a traffic shift but the removal of the *authority*: clearing one config field makes the resolver's answer inert again everywhere, restoring the exact behaviour of ADR-0139's shadow phase. That matters because the thing being canaried is not a code path's reliability but a *routing decision's authority over spend*, and "5% of spawns went somewhere nobody can name" is not a rollback story. (Receipt: `src/route_enforcement.py:canary_blast_radius` returns the enumerated set of routes the canary moves, computed from ADR-0140's `routing_matrix.build_effective_matrix` and `diff_matrices` against an empty snapshot — the whole slice is computable before the first spawn. It is a pure function with no caller in `src/` — this phase adds no surface to render it, per the non-goals — so today the receipt is one call, not a page.)

## Context

ADR-0139 built a total, pure resolver and then had every caller throw its answer away. ADR-0140 gave an operator an audited, revision-safe way to write the rule the resolver would apply. Neither changed a single spawn: legacy dials still decided all four seams, and the shadow chain recorded the disagreement.

This is the phase where the discard is removed. It is also the first phase in the epic where being wrong costs money rather than a log line, so its whole design is about bounding *who* is affected and how fast that can be undone.

Three facts about the code shape everything below.

- **The traffic a policy can bind is the traffic that already reaches the tap.** `routing_policy.LegacyRoute.governed` is transport equal to gateway. A z.ai-pinned loop making a direct OpenAI-compatible call never touches the gateway, and no gateway-side decision can reach it; ADR-0139 §D7 made that measurable and #11544 owns closing it.
- **The policy snapshot lives on the HydraFlow side.** ADR-0140 §D1 put the write plane where the read plane already was, under the repository's own data root, because the gateway container and the factory host share no filesystem. So the *route* is resolved at the spawn, not at the mint — which decides the division of labour in D3.
- **v1 mint has no caller identity.** The shared control token says nothing about who is asking, and `MintKeyRequest.provider_binding` lets the caller name its own upstream. One v1 key is therefore a policy-free lane into an enforced repository unless something structurally refuses it.

The design document's own instruction for this phase is to label the first canary agentic-only unless unsupported one-shot faces are rejected for that repository, and not to market it as an all-traffic guarantee. D1 and D4 are the two halves of taking that literally: the bound is narrow and enumerable, and every face the gateway cannot bind is refused rather than exempted.

## Decision

### D1: The canary's bound is one canonical repository × gateway transport, not a seam list

All four governed-spawn seams participate — `base_runner._execute`, `runners.base_subprocess_runner.BaseSubprocessRunner.run`, `runner_utils.run_lightweight_agent`, and `runner_utils.stream_claude_with_telemetry` — and each calls exactly one entry point, `route_enforcement.enforce_canary_route`, whose bound is a single predicate, `route_enforcement.canary_covers`. Each seam guards that call with `route_enforcement.canary_armed` first, so a host with the dial unset does not build a stage trail, does not hand a worker thread a snapshot read, and does not run one line of enforcement code per spawn — the *cost* of the canary is bounded by the same field as its behaviour.

Enforcing at a subset of seams was the tempting cheaper option and it is wrong twice over. First, the divergence rate it produced would be a property of *HydraFlow's internal layering* — which runner class happened to spawn the work — rather than of the policy, and evidence that measures the wrong variable is not evidence for arming anything wider. Second, a repository that could still mint an unbound key from *some* seam has no authorization boundary at all: D4's server-owned refusal is only meaningful if every path into that repository's spend goes through the bound one.

The transport half of the bound is load-bearing in the other direction. `canary_covers` requires `LegacyRoute.governed`, so the canary binds traffic that already transits the gateway and **never promotes a spawn onto it**. A direct-Anthropic, direct-z.ai, or OpenAI-compatible one-shot spawn inside the canary repository is outside the bound and runs byte-identical code (`test_the_canary_never_promotes_a_spawn_onto_the_gateway`). Widening the tap is a far larger change than a canary is permitted to make, and it is not this phase's to make.

| Seam | Face | How the route is applied |
|---|---|---|
| `base_runner._execute` | agentic | `apply_to_command`, then re-parse the argv |
| `BaseSubprocessRunner.run` | agentic | `apply_to_command`, then re-parse the argv |
| `runner_utils.stream_claude_with_telemetry` | agentic | `apply_to_command` on an argv the caller built |
| `runner_utils.run_lightweight_agent` | one-shot | assign `effective_model`; rebuild the telemetry descriptor |

The one-shot row is inside the bound rather than exempted, and it costs nothing extra to hold: a one-shot spawn that transits the gateway is the Claude CLI against the tap, so it reaches the same Anthropic message face D4's allow-list already binds. A one-shot spawn on a direct OpenAI-compatible backend never reaches the gateway and is outside by transport, not by exception.

ADR-0139 §D2's lossy-slug refusal is reused rather than re-implemented: `canary_covers` demands `RepoIdentityVersion.CANONICAL`, and `canary_repo` runs the configured value through `routing_policy.canonicalize_repo`. An identity that is not exactly `owner/repo` can never match the canary in either direction — a slug-derived spawn cannot fall into an armed canary, and a slug typed into the dial arms nothing.

### D2: On this side of the boundary the canary changes exactly one thing — the child's `--model`

`EnforcedRoute.apply_to_command` goes through `prompt_telemetry.rewrite_command_model`, the same writer `repo_backend.apply_repo_provider` and `credit_failover.apply_credit_failover` already use. There is no second argv rewriter to keep in step, and a seam that owns a bare model variable rather than an argv (`run_lightweight_agent`) assigns `EnforcedRoute.effective_model` and rebuilds its telemetry descriptor from it, so the recorded model is the one that ran.

HydraFlow does **not** choose the account. The v2 request carries no field that could name one, and the gateway derives the account from the model at mint time (D3) — so a policy edit cannot make HydraFlow reach for a credential the gateway did not authorise.

A `legacy-compatibility` decision returns the model the spawn already had, so `apply_to_command` returns the identical list. Arming the canary on a repository with no policy changes nothing, and `test_an_armed_canary_with_no_policy_moves_nothing` is exactly that assertion against a live seam.

A `held` or `rejected` decision raises `route_enforcement.EnforcementRefused` **before** `runner_utils.resolve_harness_env` is reached, so a refused route has no path to an ambient or direct provider credential — there is no credential in existence at the moment of the refusal. Three of the four seams collapse it onto the failure path a failed mint already takes, so they grew no new branch. `run_lightweight_agent` is the exception and deliberately so: its contract is a soft `rc=-1` rather than an exception, and it already converts the CH-6 gate's block that way — a refused route is the same shape of answer (the prompt was never sent, no telemetry row exists, and a caretaker loop retries later), so it is converted the same way rather than made to propagate out of a seam fourteen loops call.

The gateway's own refusals arrive by a different route and are collapsed onto the same path. Every well-formed attempt is answered with 200 and a decision, so a mint refusal is a *body*, not a status code — a client that only checked the status would spawn on a decision that held. `gateway_mint_client._require_selected_route_decision` turns anything but `outcome=selected` **and** `credential_state=issued` into `GatewayMintError`, carrying the reason code and never the body. The second half of that condition matters on its own: a replayed attempt reports a lease that exists and a token that is gone for good, and spawning without a credential is not an option while minting a second one is the duplicate-billing failure v2 exists to prevent.

### D3: The v2 mint takes identity and intent; the gateway derives the account from the model

`route_mint.MintV2Request` declares no `provider_binding`, no `account_id`, and no upstream, and sets `extra="forbid"`: the absence is structural, not documentary (`test_the_v2_request_declares_no_binding_field_at_all`). `models.binding_for_model` is the single definition of model→lane, and `route_shadow.provider_binding_for` delegates to it, so the mint and HydraFlow's own legacy classifier cannot disagree about which account serves a model.

This is not caller-selection with extra steps, and the division of labour is worth stating honestly. The gateway does not hold the policy snapshot, so it does not re-derive the *route* — it could not, and pretending otherwise would need a snapshot-distribution mechanism two ADRs have now deferred. It does re-derive the *account*, and it independently re-checks ADR-0139 §D4's one invariant with `driver_contracts.ModelRequirement.satisfied_by`: a literal Opus/Sonnet requirement served by an id without Anthropic provenance is `rejected` at the mint, on the far side of the trust boundary. Only the literal-family arm is re-checked, because a policy may legitimately remap a capability or a concrete request, and re-deriving more would be the gateway growing a second, divergent policy engine whose disagreements with the first would present as routing incidents.

Around that verdict, `route_mint.RouteMintStore` holds four properties:

- **One attempt, one decision, at most one lease.** Every attempt appends a decision — `held` and `rejected` are recorded exactly like `selected` — so a retry cannot be silently converted into a second lease. Only `selected` calls `keys.VirtualKeyStore.mint_bound`.
- **`mint_attempt_id` is the idempotency key, over a canonical signature.** `MintV2Request.signature` digests the entire request, so reuse with a different identity or intent is a `MintAttemptConflict` surfaced as **409** and never auto-retried: only the caller knows which of its two intents it meant.
- **A raw token exists on exactly one response.** A replay of a *selected* attempt returns the decision and the key id with `credential_state=withheld-replay` and no token. The recourse is an acknowledged revoke and a new attempt — never a second hidden lease.
- **Atomicity is one `threading.Lock` with no `await` inside the critical section**, so two racing retries cannot both mint. `test_two_threads_racing_one_attempt_id_mint_one_key` pins it against real threads rather than asserting the comment.

`route_mint.evaluate_attempt` is where the verdict is computed, and it is pure and total for the same reason ADR-0139 §D1 made the resolver so: it runs inside a lock on a live spawn path, and an exception thrown there is a routing incident. Its refusal vocabulary distinguishes two kinds of "no". `unbindable-request-face`, `repo-identity-not-canonical`, `effective-model-missing` and `literal-family-unsatisfiable` are **rejections** — the attempt was inadmissible. `account-not-configured` is a **hold**, because the route is right and only the credential is missing; reporting an operational gap as a policy verdict would send an operator to edit a policy that was never wrong. That distinction is the design's failure table read back honestly.

The attempt table is bounded. Retention is one key TTL (`GatewaySettings.max_key_ttl_seconds`), reaped by the gateway's existing reaper alongside expired keys and bodies, so a record outlives the lease it describes and nothing more. A **saturated** table `held`s rather than evicting (`mint-capacity-exhausted`): evicting a live attempt would forget a lease that still exists and licence exactly the second lease this machinery exists to prevent. The capacity refusal is answered but *not recorded* — recording it would consume a slot in the table that is already full, so a retry loop against a saturated gateway would grow it one record per attempt for a whole retention window, which is the unbounded growth the ceiling exists to prevent arriving through the ceiling. Nothing is lost by not recording: no lease was reserved, so there is no outcome a replay could need to be told about. `test_a_saturated_attempt_table_holds_rather_than_evicting` keeps that from being quietly optimised into an LRU.

The new wire models inherit ADR-0138 §D4's zero-disclosure guards by being added to the parametrize lists in `tests/test_gateway_secret_absence.py` — `MintV2Request`, `MintDecisionView`, and `RouteBinding` against the credential-shaped-field schema sweep, and the module itself against the AST `get_secret_value` sweep — rather than by growing a second set of guards next to the first. `MintV2Response` is deliberately absent from that list: it is the one model that legitimately carries a token, which is exactly why it never appears in a decision view, a key record, a ledger row, or a route view.

### D4: Enforcement is structural at the data plane, and the v1 refusal is server-owned

`models.GatewayIdentity.route_binding` is absent on every v1 key. "This key is governed" is therefore a fact the data plane reads off the resolved identity, not a claim a caller makes in a header it controls.

`RouteBinding` is fixed at mint and never renegotiated, so a policy edit affects the *next* key and never this one — the design's "no silent or mid-session rerouting" rule, held by the shape of the object rather than by a convention. It carries the account, the effective model, and the policy lineage (`policy_id`, `policy_revision`, `snapshot_hash`, `route_decision_id`), which is what makes the resulting ledger row joinable back to the decision that authorised it.

For a route-bound key, `proxy.GatewayProxy._bind_governed_request` buffers and parses the **whole** body before any `httpx.Request` exists, and `governed_preflight.check_governed_body` compares its `model` with `RouteBinding.effective_model`. A streamed check is a check performed after the bytes have left, and the design says it outright: merely observing a model after bytes reached upstream is not enforcement. Three details follow from that:

- **The supported face set is an allow-list.** `governed_preflight.GOVERNED_MESSAGE_PATHS` names `/v1/messages` and `/v1/messages/count_tokens` and nothing else; anything else is refused with `unsupported-request-path` — a distinct code from the mint's `unbindable-request-face`, because one means "this HTTP path is not in the allow-list" and the other means "this spawn's request face cannot be reasoned about at all", and an operator grepping the logs for one must not find the other. A face this module cannot parse is a face it cannot bind.
- **Duplicate JSON keys anywhere in the body are refused.** `json.loads` resolves duplicates last-write-wins, so two parsers can legitimately disagree about what a body says — and a body whose meaning depends on the parser cannot be checked against a binding (`test_a_duplicate_key_elsewhere_in_the_body_is_still_refused`).
- **A refusal never quotes the body.** `GovernedRequestRefused` carries only its `PreflightRefusal` code, because these exceptions reach the gateway's logs and a governed request body is a prompt.

The v1 side is the other half. `GatewaySettings.governed_repo_slugs` (env `GATEWAY_GOVERNED_REPOS`, empty by default) makes `POST /control/v1/keys` refuse a governed repository outright, and makes the proxy turn away an unbound key **already in flight** with `unbound-governed-key` before a single byte is read from the client. The design's own words are the reason it is a server-side allow-list rather than a request field: a declaration alone is not an authorization boundary, so the set is owned by the deployment and cannot be asserted by the caller.

The two ends of the canary name a repository in two identity spaces — HydraFlow's dial is the canonical `owner/repo`, while a mint request and a resolved identity both carry the path-safe `owner-repo` — so `settings._governed_repo_allowlist` accepts either and stores the runtime slug. It is a *separate* parser from `_repo_slug_allowlist`, which the body-capture allow-list uses: that one is matched against whatever `MintKeyRequest.repo_slug` carries — a caller-supplied string with no guaranteed form — so normalising it would silently de-authorise a repository whose slug does not round-trip. Same shape, different semantics, and sharing one function conflated them. An operator copying the canonical form out of `.env.sample` would otherwise get an allow-list that can never match, and a security control that fails open on a format difference, with no log line and no startup error, is worse than no control.

### D5: Two switches, one rollback, and the ordering is stated rather than discovered

The operator-facing rollback is HydraFlow's `config.gateway_enforcement_canary_repo`. It is live — `settings_registry` declares `SettingSpec(live=True)` and `route_enforcement.canary_repo` re-reads it at every spawn — empty by default, and clearing it disarms every clause of D1 on the **next** spawn: no restart, no policy edit, no gateway change, and the policy snapshot left untouched on disk so nothing has to be re-authored to arm again (`test_the_rollback_leaves_the_policy_snapshot_on_disk`).

| Switch | Side | Default | What it does |
|---|---|---|---|
| `config.gateway_enforcement_canary_repo` | factory host, live per spawn | empty | Arms and disarms the whole of D1. The operator control. |
| `GatewaySettings.governed_repo_slugs` | gateway deployment, read at boot | empty | Refuses v1 mint and unbound keys for a repository (D4). |

The gateway's `governed_repo_slugs` is a *deployment* hardening that lives on the other side of a trust boundary, and it therefore cannot be cleared by the same action. The consequence has to be stated plainly rather than discovered during an incident: if an operator clears the HydraFlow dial while the gateway still governs that repository, that repository's v1 mints are refused and its gateway spawns fail **closed** — loudly, with a typed reason, and in the safe direction for a security boundary — rather than falling through to an ungoverned lane. That is the correct behaviour for the boundary and the wrong surprise for an operator who thought they had rolled back.

Hence the documented ordering: **arm the spawn side first and the gateway second; disarm the gateway last.** Because `governed_repo_slugs` is empty by default, the *shipped* canary is armed and disarmed by one HydraFlow field, and that is precisely what the "restores prior behaviour exactly" regression covers at both agentic seams.

ADR-0138 §D5's disposition, recorded so nobody has to re-derive it: it scopes its restriction to the **dashboard's** write plane, and this phase adds no dashboard route at all. The write boundary ADR-0140 built is untouched, and the canary's dial is an ordinary settings field behind that same boundary.

## Non-goals — what this phase deliberately does not build

**One repository, one transport, one switch.** The phase is defined by these.

- **No fleet-wide enforcement, and no percentage rollout.** One canonical repository, named in full.
- **No bounded fallback.** No `retry_of_decision_id`, no `supersedes_decision_id`, no fallback position, no revoke-then-remint protocol. A lost mint response fails the spawn closed; the acknowledged-revoke-and-supersede handshake belongs to #11540, with the capacity model that needs it.
- **No multi-account pools and no ordered selection across accounts** (#11540). The only accounts in existence are still ADR-0138's two legacy bindings.
- **No `forbid_direct_bypass` enforcement.** ADR-0139 left the field recorded and inert; the direct one-shot HTTP backends still bypass the gateway entirely, and #11544 measures it.
- **No widening of the governed face allow-list.** The compatibility probe the design asks for — enumerating every Claude CLI request face and auxiliary call — is not run here. Until it is, an unenumerated face is refused rather than waved through.
- **No durable gateway-side decision store, and no `/control/v2/decisions/{id}`.** The attempt table is process-local (see Consequences), and the durable, hash-linked record of *why* a spawn routed where it did is still ADR-0139's chain on the HydraFlow side. `mint_decision_id` on the ledger row and the route views is the pointer into the gateway's half; a second durable history is only worth building once there is a second consumer for it.
- **No dashboard surface for the canary.** No new route, no UI. The dial is a settings field, and the blast radius is a function over a matrix ADR-0140 already exposes.
- **No retirement of any legacy dial** (#11543 / P6). Role dials, `repo_provider`, the fleet ratchet and ADR-0119 credit failover all still decide every spawn outside the canary — and still decide the *input* route inside it, which is what the resolver is handed.

## Consequences

- **A resolver bug is now a routing incident, not a bad log line.** This is the first phase in which a routing decision changes what is spawned. That is why the predicate is evaluated before anything else runs, why `EnforcementRefused` is raised before a credential exists, and why the refusal path is fail-closed at every seam rather than degrading to legacy.
- **A governed request is no longer streamed to the upstream.** Its body is buffered to `GatewaySettings.max_request_bytes` (32 MiB by default) before the upstream request is constructed, and that is a real latency and memory change for the affected traffic — not a free property. It is acceptable **for the canary slice only**: the ceiling already existed and already applied, and the slice is one repository's gateway traffic. Any widening re-opens this question rather than inheriting the answer.
- **The shadow chain keeps recording for the canary repository too.** Every seam records the ADR-0139 observation *before* it asks about enforcement, so agreement and divergence stay measurable while enforcement runs. `route_decision_id` on the ledger row, the lease view, the in-flight view and the terminal view is the join back to that chain; `mint_decision_id` is the gateway's own per-attempt identity, and the two are deliberately different ids.
- **A canary spawn reads and hash-verifies the snapshot twice.** The shadow recorder loads it to observe, and `enforce_canary_route` loads it again to decide, both on a worker thread. Sharing one load between them would couple the observation to the enforcement and make an inert shadow depend on an armed canary — the wrong trade at this size. Two reads of a small file per spawn is the price of keeping ADR-0139's inertness intact while enforcement runs beside it.
- **Idempotency is process-local.** A gateway restart forgets the attempt table, so an attempt id replayed across a restart can mint a second lease. It is bounded by the key TTL, accepted for a canary of one repository, and named here rather than hidden — a durable attempt store is the follow-up if the slice ever widens.
- **Both request faces inside the bound are enforced, and they move differently.** The three agentic seams rewrite an argv and then re-read it with `prompt_telemetry.parse_command_tool_model`, so the model the mint is told about is the model the child was actually spawned with; `run_lightweight_agent` owns a bare model variable and rebuilds its telemetry descriptor from it. Two writers for one decision is the kind of asymmetry that produces a ledger row disagreeing with the process that produced it, so both are pinned rather than assumed.
- **The canary is inert for any repository whose gateway traffic is zero.** Arming it on a repository that reaches the gateway through neither the fleet ratchet nor a gateway dial measures nothing at all. An operator has to read `canary_blast_radius` rather than assume the dial did something.
- **Two switches now exist and only one is an operator control.** D5's ordering is a documented operating procedure, not a property the code can enforce from either side of the trust boundary.

## Alternatives considered

- **Ship the snapshot to the gateway and resolve there** — which is what the design proposal's route-aware mint literally describes. Rejected, and recorded as an explicit disagreement with the design document the way ADR-0140 §D1 did, because the prose is what a reader finds first: it needs a snapshot-distribution mechanism ADR-0139 and ADR-0140 both deferred with reasons that still hold, it makes every spawn depend on a reachable gateway for a *routing* answer, and the gateway container and the factory host share no filesystem.
- **Canary by percentage of spawns.** Rejected: the slice is not enumerable, so nobody can say before or after which spawns it touched, and the rollback is a traffic shift rather than a removal of authority — the dial would still be live at 0%.
- **Enforce at only one seam.** Rejected on both grounds in D1: the resulting divergence rate would measure HydraFlow's layering rather than the policy, and any unenforced seam is an authorization hole through which the governed repository can still obtain an unbound key.
- **Let the proxy observe the model and log a mismatch instead of refusing.** Rejected — the design says it outright, and the arithmetic is unarguable: by the time the mismatch is observable the paid request has already happened against the account the binding was supposed to protect.
- **Derive the account on the HydraFlow side and send it with the mint.** Rejected: that is caller-selected binding wearing a new name. It reintroduces exactly the v1 property D4 exists to refuse, and AC1 of #11539 forbids it.
- **Let a caller declare its own repository governed on the v1 request, so no gateway deployment change is needed.** Rejected in the design's own words and again here: a declaration alone is not an authorization boundary. The one thing the allow-list has to survive is a caller that would rather not be governed, and a field that caller controls survives nothing.
- **Keep the mint synchronous with the resolver by resolving inside `resolve_harness_env`.** Rejected: the seam that owns the argv is the seam that must rewrite it, and resolving where the credential is minted would put the decision *after* the command was built — leaving a window in which the spawn's model and the lease's model are two different facts. Resolving at the seam and threading `EnforcedRoute` through keeps them one.
