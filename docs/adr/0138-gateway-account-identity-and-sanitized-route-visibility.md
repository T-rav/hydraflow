# ADR-0138: Gateway account identity and sanitized route visibility

**Status:** Accepted
**Date:** 2026-08-22
**Enforcement:** enforced
**Binds:** factory
**Supersedes:** none
**Superseded by:** none
**Related:** [ADR-0085](0085-secrets-never-persist-in-audit-stream.md) (the canonical secret-pattern set this reuses as its absence detector), [ADR-0110](0110-provider-harness-backend-split.md) (the provider/harness binding an account is compiled from), [ADR-0119](0119-credit-failover-to-glm.md) (the failover that may change which account serves a spawn — unchanged here), [ADR-0134](0134-per-repo-model-harness-selection.md) (per-repo routing preference, which this phase observes but does not alter), [ADR-0137](0137-fenced-issue-driver-and-director-runtime-boundary.md) (`src/driver_contracts.py:WorkerRole`, the role vocabulary this reuses rather than re-declaring). Design source: `docs/proposals/gateway-routing-control-plane.md`. Issues: #11534 (this phase), #11531 (the epic), #11528 (the honest cost/usage attribution this reads), #11536 (the policy resolver this unblocks).

**Enforced by:**
pytest:tests/test_gateway_secret_absence.py
pytest:tests/test_gateway_accounts.py
pytest:tests/test_gateway_active_routes.py
pytest:tests/test_gateway_control_v2_read_api.py
pytest:tests/test_dashboard_gateway_routes.py
pytest:tests/scenarios/test_gateway_account_visibility_scenario.py

**Precedent:** Read models separated from the write path — the CQRS/read-model tradition in which a query surface is a *projection* over authoritative state rather than a second source of truth (Young, "CQRS Documents", 2010; Fowler's `CQRS` bliki entry).
**Divergence:** classical read models assume the projection may lag the write model harmlessly, but here a stale or partial projection is a *safety* claim an operator will act on ("no account is degraded", "nothing is routing"), so this projection never renders absence as a fact: every time-derived field publishes its own `window_seconds`, `as_of`, and `evidence_since`, an evicted ring announces itself as `truncated`, and an unreachable source returns a typed `source_state` instead of an empty list (receipt: the v1 gateway's `/healthz`, which reported only "providers configured" and was read as health — `docs/proposals/gateway-routing-control-plane.md` §"Current state and gaps", and its §"Vocabulary: do not call everything active").

## Context

The v1 session-tap gateway is deliberately small. `GatewaySettings.upstreams` is a dictionary keyed by provider binding, so there is at most one Anthropic and one z.ai-harness upstream; the mint caller picks the binding directly; the proxy performs exactly one attempt against that immutable binding; and the request ledger records the outcome. `VirtualKeyStore.active_count` is total-only and private, and `/healthz` reports a list of configured provider names.

That leaves an operator with no answer to four separate questions, and — worse — one badge that invites them to be confused for each other:

1. **Which accounts exist, and is each one actually configured?** A provider whose environment pair is unset is simply absent from `upstreams`; nothing names it, so "z.ai is missing" and "z.ai is fine" look identical from outside.
2. **Is an account being used right now?** There is no in-flight registry. A key can be minted and never used; a request can be streaming for ten minutes. Both are invisible.
3. **What did a route actually serve?** The ledger has this (#11528 made its cost and usage semantics honest), but nothing exposes it.
4. **Is the account healthy?** The settings UI's "key detected" badge proves only that an environment variable is non-empty. It is not health, and it is not evidence that traffic is using the account.

Epic #11531 turns the gateway into a routing authority with project policy and enforcement. Its own delivery principle is **observe before enforce**, and its P0 (#11534) is exactly this: make accounts and routes *visible and provable* without changing a single routing decision. Every later phase — the policy resolver (#11536), the policy workspace (#11538), the enforcement canary (#11539) — joins against the identities and the vocabulary fixed here. If they are wrong, wrong is what gets enforced.

Two constraints make this phase harder than a read endpoint:

- **A credential must never cross the boundary**, and neither may anything that could reconstruct or fingerprint one. This is not a code-review promise; it has to be a test.
- **The account vocabulary must not collapse.** The design document is explicit: *do not call everything "active"*. `configured`, `enabled`, `leased`, `in_flight`, `observed`, `degraded`, and `unverified` are independent facts about different things, and an operator who reads "healthy" as "currently routing" will make a bad call during an incident.

## Decision

### D1: A legacy environment pair compiles into a stable account identity derived from the binding

`src/hydraflow_gateway/models.py:LEGACY_ACCOUNT_IDS` maps each `ProviderBinding` to a deterministic, non-secret id: `legacy-anthropic` and `legacy-zai-harness`. `src/hydraflow_gateway/accounts.py:build_accounts_view` emits one account per binding **whether or not it is configured**, so a missing credential is a named account with `configured=false` and health reason `credential-missing` rather than a silent absence.

The id is derived from the binding, never from credential material. There is deliberately no hash, digest, or truncation of a key anywhere in the identity — a stable credential fingerprint is exactly as forbidden as the credential, because it lets an observer correlate "this account" across deployments and confirm a guessed key.

An account publishes: id, display name, provider binding, the upstream **origin** (scheme + authority, path dropped), auth style, and the **name** of the environment variable that configures it. The environment variable's *name* is operational documentation — it is what an operator needs in order to fix an unconfigured account — and is not a secret. Its value never leaves the process.

Multi-account pools from a server-owned definition file are a later phase (#11540). These two ids remain the deterministic identity of the legacy environment pairs, so later account definitions add ids rather than renaming these.

### D2: Account state is a set of independent facts, and an unknown result is never healthy

`AccountView` carries each fact in its own field:

| Field | Means |
|---|---|
| `configured` | The gateway resolved a credential for this binding at startup. |
| `administrative_state` | `enabled` / `draining` / `disabled`. **P0 has no administrative overlay**, so every account reads `enabled`; the type exists so #11540 can add the overlay without a wire break. |
| `leased` / `lease_count` | At least one unexpired virtual key is bound to this account. |
| `in_flight` / `in_flight_count` | At least one authenticated request is streaming through it *right now*. |
| `observed` / `observed_request_count` / `last_observed_at` | A terminal route used this account inside the published window. |
| `health` + `health_reason` | `unverified` / `healthy` / `degraded`, with a reason **code** (not prose). |

Three rules make this honest rather than decorative:

- **`unverified` is the default, and it is not a failure.** An account with a credential but no terminal evidence in the window is `unverified` with reason `no-evidence`. It is never `healthy`. The UI renders `unverified` in a neutral tone, never a success tone.
- **A client abort is not evidence about the account.** `GatewayRequestStatus.CLIENT_ABORTED` rows count as *observed* traffic (the account was reached) but are excluded from the health denominator entirely — a worker that hung up says nothing about the upstream. Four aborts in a row leave an account `unverified`, not `healthy` and not `degraded`.
- **Degradation needs a floor and a ratio.** `accounts.py:derive_health` requires both `DEGRADED_MIN_ERRORS` (3) qualifying failures and a `DEGRADED_ERROR_RATIO` (0.5) share of them before flipping to `degraded`, so one bad request is noise rather than a red badge.

**`eligible` is deliberately absent from the account model.** Eligibility means "this account can satisfy *this* repo, role, request face, and model requirement at *this* policy revision" — it is a property of a route explanation, not of an account, and computing it requires the resolver this phase does not build. The overview counts configured / enabled / leased / in-flight; it never counts "eligible ones".

### D3: The in-flight registry is written only from the proxy's single idempotent terminal chokepoint

`src/hydraflow_gateway/active_routes.py:ActiveRouteRegistry` is registered from `GatewayProxy.forward` immediately after the attempt is constructed, and released inside `GatewayProxy._finalize_attempt` — in a `finally`, so a failed ledger append still clears the row.

This placement is the whole design. `_GatewayAttempt.finalize` is already guarded by a `finalized` flag and is already the *only* way an attempt terminates: telemetry-unhealthy rejection, oversized body, client disconnect before the first chunk, upstream transport error, `asyncio.CancelledError`, a normal stream close, and the `_ObservedStreamingResponse` abort path all funnel through it. Registering beside that chokepoint means the lifecycle cannot drift from the ledger's: there is no second code path that could leave a phantom "streaming" row behind an issue that finished an hour ago. Shutdown is the one terminal event *not* expressed as an attempt, so the app lifespan's `finally` calls `registry.clear()` explicitly.

Recent evidence is a bounded ring (`DEFAULT_RECENT_CAPACITY` = 200) fed with the same `GatewayLedgerRow` that is persisted, so the Live view and the ledger cannot disagree about what was served. The ring is process-local and resets on restart; the read model publishes `evidence_since` (when this process began observing) and `truncated` (whether the ring has already evicted), so the dashboard can never present it as a complete history.

### D4: Zero credential disclosure is a machine-checked property, not a convention

`tests/test_gateway_secret_absence.py` builds a gateway with credential-*shaped* values (`sk-ant-…`, a 32-byte control token), drives a lease, an in-flight route, and a terminal route through it, then asserts against every v2 read payload that:

- neither upstream provider key, the control token, the minted virtual token, nor the token's secret half appears;
- the captured-body handle (`body_capture_id`) — an addressable pointer to raw prompt and response bytes — is not published;
- `secret_scrub.scan_for_secrets` (ADR-0085's canonical detector) finds nothing to redact;
- no read model *declares* a field whose name contains `token`, `secret`, `api_key`, `digest`, or `fingerprint` — a schema-level guard that fails on a future field before it can ever be populated;
- neither projection module calls `get_secret_value` anywhere (AST sweep), so a `SecretStr` cannot be unwrapped into a view;
- and — the assertion that keeps the others from being vacuous — the sanitized join key that *is* meant to be published **is** present.

**On `key_id`.** The lease row publishes `key_id`, and this is deliberate. A virtual token is `hfgw_{key_id}.{secret}`: `key_id` is a random ULID, the entropy is the separate 32-byte `secret` half, and only a SHA-256 digest of the *whole* token is retained. `key_id` therefore cannot reconstruct a credential, it is already the ledger's non-secret correlation column, and #11540's `revoke-leases` action needs it to name a lease. Publishing it is a considered disclosure of a random identifier, not of key material — and `test_read_payloads_carry_no_virtual_token_secret_half` pins the distinction.

### D5: HydraFlow proxies the read plane; the browser never holds a gateway credential

The three gateway endpoints live under `/control/v2/` so the existing `_ControlPlaneBoundary` ASGI middleware authenticates them **before** body parsing, exactly like v1 mint. HydraFlow's dashboard exposes `/api/gateway/accounts`, `/api/gateway/routes/active`, and `/api/gateway/routes/recent`, backed by `src/gateway_control_reader.py:GatewayControlReader`, which holds the env-only `HYDRAFLOW_GATEWAY_CONTROL_TOKEN`, calls the gateway with `trust_env=False`, and **validates every payload against the gateway's own read models** before returning it — so a schema drift fails closed as `source_state=invalid` rather than reaching the browser unchecked.

Every proxy response is an envelope: `{available, source_state, data}`. `source_state` is `available`, `not-configured` (no control token on this host), `unreachable`, or `invalid`. An unavailable source returns `data: null` and a 200, so the panel renders an explicit degraded message naming the fix — never an empty account list that reads as "no accounts exist".

**The boundary of record, stated plainly:** HydraFlow's dashboard has no in-process authentication. Its operator boundary is the loopback socket bind (`config.dashboard_host`, default `127.0.0.1`). Terminating the gateway's bearer boundary there is acceptable *for this phase precisely because* D4 holds and the surface is read-only: everything proxied is non-secret, and there is no mutation route to reach. **Any later phase that adds a gateway write route through this proxy must gate it on an authenticated operator identity, and must be disabled when the dashboard is bound beyond loopback** — that requirement is a precondition on #11538, not a nice-to-have.

### D6: Roles join to the ADR-0137 catalog by exact match, or not at all

The gateway publishes the observed principal (`principal_kind`, `principal_id`) verbatim; it does not invent a role. The HydraFlow proxy adds `worker_role` via `gateway_control_reader.canonical_worker_role`, an **exact, case-insensitive match** against `src/driver_contracts.py:WorkerRole` — the vocabulary ADR-0137 already fixed. A principal that is a loop name (`adr_review`), a person, or anything else stays `null`.

A heuristic here would be worse than no join: #11536's resolver matches on canonical `WorkerRole`, and a fuzzily-guessed role in the observation layer would disagree with the resolver's own answer and be read as a routing bug. The UI falls back to displaying the raw principal id, which is what an operator recognises anyway.

## Non-goals — what this phase deliberately does not build

These are not omissions; the phase is defined by them. **Observe before enforce.**

- **No routing or mint change.** The provider binding is still chosen by the mint caller. `repo_provider`, the role-provider dials, the fleet ratchet, and ADR-0119 credit failover are untouched. The pre-existing golden direct-versus-gateway conformance replay (`tests/test_gateway_conformance.py`) passes unchanged, which is the proof.
- **No policy engine.** No `routing_policy.py`, no `routing_store.py`, no resolver, no explain / dry-run / batch endpoints, no policy revisions or audit chain. That is #11536 and #11538.
- **No writes at all.** No `PATCH .../state`, no `revoke-leases`, no administrative overlay. `administrative_state` exists as a *type* and always reads `enabled`.
- **No multi-account registry.** No `GATEWAY_ACCOUNTS_FILE`, no pools, no ordered selection, no capacity reservation (#11540).
- **No new control-credential scopes.** The design's read / mint / policy-admin split arrives with the first write route; P0 reuses the single existing control token.
- **No repository scoping on the read routes.** Accounts are host-global and every route row carries its own `repo_slug`. Filtering a repo's view is part of the effective-routes matrix (#11536/#11538); filtering here would risk *hiding* traffic, which is the opposite of this phase's job.

## Consequences

- **The vocabulary is now fixed for the epic.** #11536 can join a resolver decision to `account_id` and `worker_role` without inventing identities, and can add `eligible` where it belongs — inside an explanation.
- **The dashboard gains a third global, idle-exempt mode.** `?mode=routing` with `routingView=accounts|live`, following the design's reserved sub-view keys so `effective`, `policies`, and `audit` slot in later without a URL break. Idle-exempt for the same reason Instruments and Supervisor are: "is any account even configured?" is a question asked precisely when the factory is quiet.
- **Recent evidence is process-local.** A gateway restart empties the ring even though the durable ledger still holds the rows. This is accepted for P0 — `evidence_since` makes it honest, and a ledger-backed recent view can be added later without changing the wire shape.
- **Health thresholds are module constants, not configuration.** `DEGRADED_MIN_ERRORS` and `DEGRADED_ERROR_RATIO` are code-owned. They are a first calibration over passive evidence with no field data behind them yet; making them env knobs would invite tuning a number nobody has measured. The evidence window *is* a bounded query parameter, because that is the one an operator legitimately varies.
- **The read plane costs nothing to serve.** All three endpoints read in-memory structures; there is no file scan per poll. The dashboard polls them at `GATEWAY_ROUTING_POLL_MS` (30s), and both `limit` and `window_seconds` are server-bounded so a read cannot become a scan.

## Alternatives considered

- **Serve recent routes by tailing the ledger file.** Durable across restart, and the honest "complete history". Rejected for P0: it makes a dashboard poll an O(file) scan of an append-only log that grows without bound, and it needs a tail-read seam `AppendOnlyJsonlLedger` does not have. The ring holds the same rows the ledger holds, and `evidence_since` prevents it from overclaiming. Revisit when an operator actually needs pre-restart history.
- **Derive account health from an active probe.** Rejected, and the design document rejects it too: a background probe burns paid model calls to answer a question passive evidence already answers, and an unknown probe result would still have to be `unverified`.
- **Import `WorkerRole` into the gateway package and do the role join server-side.** Rejected for this phase. The gateway deployable stays free of HydraFlow's driver contracts until a phase actually needs them to *decide* something (#11536's resolver does). Joining on the HydraFlow side, where `driver_contracts` is native, keeps the boundary clean and costs one pure function.
- **Fold Accounts and Live into the existing Instruments mode.** Rejected: Instruments is the noise-floor / control-register surface, and the routing workspace has five reserved views coming. A dedicated mode with a sub-view parameter is the shape the design already specified.
- **Gate the proxy routes behind a loopback check.** Rejected for a read-only, zero-secret surface — it would be enforcement this phase is not authorised to add, and the design scopes the loopback restriction to policy *writes*. Recorded in D5 as a hard precondition on the first write route instead.
