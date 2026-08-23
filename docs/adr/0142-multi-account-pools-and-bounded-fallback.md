# ADR-0142: Multi-account pools and bounded fallback

**Status:** Accepted
**Date:** 2026-08-22
**Enforcement:** enforced
**Binds:** factory
**Supersedes:** none
**Superseded by:** none
**Related:** [ADR-0085](0085-secrets-never-persist-in-audit-stream.md) (the credential-absence guards every new wire model is added to), [ADR-0110](0110-provider-harness-backend-split.md) (the provider/harness binding an account compiles from), [ADR-0119](0119-credit-failover-to-glm.md) (the legacy mechanism whose failure classes this borrows a vocabulary from and does not retire), [ADR-0137](0137-fenced-issue-driver-and-director-runtime-boundary.md) (`WorkerRole` and `ModelRequirement`, carried rather than re-declared), [ADR-0138](0138-gateway-account-identity-and-sanitized-route-visibility.md) (account identity, the `administrative_state` *type* this phase finally populates, and §D5's dashboard write-boundary precondition), [ADR-0139](0139-shadow-routing-policy-resolver.md) (the resolver and its account-rejection vocabulary), [ADR-0140](0140-revision-safe-policy-workspace-and-operator-write-boundary.md) (the revision-safe write pattern reused here for account state), [ADR-0141](0141-bounded-reversible-routing-enforcement-canary.md) (the mint this extends, and the phase that deferred every word of this one). Design source: `docs/proposals/gateway-routing-control-plane.md` §"P4 — multi-account pools and bounded fallback". Issues: #11540 (this phase), #11531 (the epic), #11539 (the phase this builds on), #11544 (the phase this unblocks).

**Enforced by:**
pytest:tests/test_routing_accounts.py
pytest:tests/test_routing_account_state.py
pytest:tests/test_routing_account_admin.py
pytest:tests/test_routing_fallback.py
pytest:tests/test_route_mint.py
pytest:tests/test_gateway_secret_absence.py
pytest:tests/architecture/test_gateway_env_key_coverage.py
pytest:tests/regressions/test_issue_11540_pool_is_default_inert.py
pytest:tests/scenarios/test_gateway_account_pool_scenario.py

**Precedent:** Connection-pool health checking with a circuit breaker and a bounded retry budget — Nygard's *Release It!* (Circuit Breaker, Bulkhead), Hystrix/resilience4j's bulkhead-per-dependency, and the "retry budget" pattern that replaced naive per-call retries in Envoy and gRPC.
**Divergence:** the classic circuit breaker retries the *same* logical call against another instance of one fungible service, and the retry budget bounds a rate. Here the alternatives are **different billing identities**, so a retry is not a retry: it is a second lease, against a second account, that will be invoiced separately. That inverts what the bound is for. A rate budget would still permit duplicate spend inside it; what has to be bounded is the number of *authorised leases per logical dispatch*, and the authority to create the next one has to come from evidence the gateway itself holds rather than from the caller reporting a failure. Hence a hop advances only on a new attempt, only after the prior lease is provably released, only on the gateway's own terminal row, and only within a ceiling counted in hops rather than in seconds. (Receipt: #11540's own acceptance criterion — "no mid-request retry, hidden second lease, token replay, or duplicate billing" — and ADR-0141 §D3, which built the one-attempt-one-lease invariant this must not break. `tests/scenarios/test_gateway_account_pool_scenario.py` drives a real 429 through a real two-account pool and asserts the retry reached a *different upstream host* with exactly one live lease across the whole hop.)

## Context

ADR-0138 compiled two environment pairs into two account identities and declared `administrative_state` as a type that always read `enabled`. ADR-0139 built a resolver whose `RoutingAction` already carried `account_pool`, `selection`, `on_unavailable` and `fallback_on` — every one of them inert. ADR-0141 removed the discard for one repository and, in its non-goals, deferred all of this by name: "no bounded fallback… no multi-account pools and no ordered selection… The only accounts in existence are still ADR-0138's two legacy bindings."

Three facts about the code shape everything below.

- **Only the gateway can choose an account.** ADR-0141 §D3's whole claim is that the v2 mint takes identity and intent, and that the gateway derives the account itself — "derive the account on the HydraFlow side and send it with the mint" was rejected there as caller-selected binding wearing a new name. A pool cannot be a field HydraFlow fills in without reopening exactly that.
- **The gateway holds no policy snapshot.** ADR-0140 §D1 put it on the HydraFlow side. So the policy's `account_pool` and `fallback_on` cannot reach the gateway, and D2 below says plainly what that costs.
- **A second account on one lane is unreachable by the existing data plane.** `GatewaySettings.upstreams` is keyed by `ProviderBinding` — one origin and one credential per provider. Everything else here is downstream of fixing that.

## Decision

### D1: A pool is opt-in, additive, and totally ordered — legacy accounts first

`GATEWAY_ACCOUNTS_FILE` names a server-owned document (`routing_accounts.parse_account_definitions`) that declares *additional* accounts. It is absent by default, and with it absent the registry is exactly ADR-0138's two compiled identities, every candidate list has one entry, and no hop has anywhere to go. **Turning on a pool cannot move a single request on its own**, because the reserved legacy accounts lead the order and declared accounts follow in file order: the account already serving today's traffic keeps serving first, and a declared account is a *fallback target* rather than a silent promotion. `tests/regressions/test_issue_11540_pool_is_default_inert.py` is that property rather than this paragraph.

Redeclaring a reserved id is refused. Two definitions of one account is exactly the ambiguity an ordered pool exists to remove, and a file that could rewrite `legacy-zai-harness`'s origin could re-point v1 traffic without touching a v1 setting.

**No credential is ever in the file.** An account names the *variable* that configures it, and `GatewayAccount.validate_credential_env` requires that name to match `GATEWAY_[A-Z0-9_]+`. That is not cosmetic: `subprocess_util.scrub_gateway_spawn_env` is what keeps a worker from inheriting a real provider credential, and an operator-chosen variable name cannot be enumerated in a hand-maintained set in advance. The naming rule makes the whole `GATEWAY_` namespace scrubbable by prefix, so a declared account's credential is stripped from every spawn by construction rather than by remembering to add a row. The hand-maintained set had already drifted once (a #11653 review found `GATEWAY_GOVERNED_REPOS` missing from it), so `tests/architecture/test_gateway_env_key_coverage.py` now AST-reads the literals `GatewaySettings.from_env` actually consumes and fails when one is not scrubbed — with a non-vacuity assertion, because an extractor that silently returns an empty set passes forever.

**Capacity is `None` by default.** A legacy account has never had a ceiling, and inventing one here would turn an additive registry into a throughput change for every deployment that never asked for a pool.

### D2: The gateway owns selection, and the policy's fallback vocabulary stays inert — stated, not hidden

Selection is `routing_account_state.select_account`: it walks `AccountRegistry.candidates_for_model` — the *static* answer, a pure function of the model and the registry — and returns the first candidate not ruled out by a live fact, with a code for every candidate it passed over.

The static/live split is the load-bearing part. The candidate *set* and its positions are stable and replayable; only the filters vary. A fallback position computed against a set that had since changed shape would advance onto a different account than it named.

Five live filters, ordered cheapest-and-most-permanent first, because reporting the *first* one is what makes the code actionable: `not-configured` (a deployment fact), `administrative-disabled` and `administrative-draining` (an operator's decision), `circuit-open` and `lease-capacity-exhausted` (transients). An account that is both disabled and full needs the operator to re-enable it, not to wait.

**And the honest cost.** The policy's `RoutingAction.account_pool`, `selection`, and `fallback_on` remain recorded and inert, exactly as ADR-0139 left them, because the gateway has no snapshot to read them from. Concretely: an operator cannot yet narrow a pool or narrow the qualifying failure classes *per policy*; the gateway's registry order and its own fixed qualifying set decide. This is a smaller capability than the design document describes, and it is the smaller one deliberately — the alternative was to let HydraFlow send the pool and the conditions with the mint, which is caller-selected binding by another name and would have reopened ADR-0141 AC1. Narrowing per policy needs the snapshot on the gateway side, which two ADRs have now deferred with reasons that still hold. #11544 owns it.

The qualifying set the gateway *does* own is deliberately narrow, and its exclusions carry as much weight as its inclusions (`routing_fallback.condition_for_terminal`): a **client abort** says nothing about the account, so it is never a licence to move — the same reason `accounts.derive_health` excludes it from a health verdict. An ordinary **4xx** is the caller's own malformed request; licensing a hop on one would let a worker walk a whole pool by sending four bad bodies, spending a lease against every account on the way. Credit exhaustion is recognised only from a status code (402), and this deliberately does not read the response body a provider often signals it in: the body of a governed exchange is a prompt, and a routing rule that had to read one would put prompt content into a routing decision.

### D3: Two ceilings, counted separately, released exactly once by construction

Lease admission and request admission are different questions and are counted in two independent tables (`AccountRuntimeState`). A burst of minted keys that never sends a request must not consume an account's concurrent-request budget, and a long stream must not consume a lease slot twice. The lease is reserved at the mint, inside the same lock that records the decision; the request slot is taken at the proxy after identity resolution. **The gateway never waits** — the design says so outright — so an account at its request ceiling answers 429 and the caller's own retry decides what happens next.

Exactly-once release is a property of the data structure, not of four call sites remembering to be careful. **Reservation is keyed on a holder** — the key id for a lease, the request id for a request — recorded in a dict. Reserving one holder twice consumes one slot; releasing one holder five times returns one slot; releasing a holder that never reserved does nothing. `VirtualKeyStore.on_release` is the single seam every path that ends a key funnels through — explicit revoke, expiry noticed on `resolve`, the reaper, and an account-wide revocation — and the dict removal is what decides, so the callback fires once per key however many paths raced to end it. The request slot is released in `_GatewayAttempt.finalize`'s `finally`, beside the in-flight `discard` and for the identical reason: a raise inside `_finalize_attempt` would otherwise leak one slot per crashed finalize for the process lifetime.

Selection's capacity check is **advisory** and says so: it takes and releases the capacity table's own lock, and only the reservation decides. A mint whose reservation fails after selection revokes the key it just minted rather than leaving a lease outside the ceiling for a whole TTL.

### D4: A hop is a new attempt, licensed only by the gateway's own terminal evidence

`MintV2Request` gains `retry_of_mint_decision_id` and `supersedes_mint_decision_id`, mutually exclusive, and **neither names an account**. A citation can only move the gateway's own scan further down a list the gateway computes; ADR-0141 AC1 survives intact.

`routing_fallback.authorise_fallback` is pure and total, and its clause order is the order of severity so that a caller bug is never reported as a transient hold a retry loop would hammer:

| Refusal | Disposition | Why |
|---|---|---|
| `fallback-lineage-unknown` | held | The citation may be a restart after a gateway restart; the attempt starts nowhere rather than at position 0. |
| `fallback-cited-decision-not-selected` | **rejected** | Citing a decision that never took a lease is a caller error. |
| `fallback-lineage-mismatch` | **rejected** | Different dispatch, repository, or effective model — not this dispatch's fallback. |
| `fallback-lease-still-held` | held | Revoke-then-remint, enforced rather than documented. |
| `fallback-not-authorised` | held | No qualifying terminal row. Caller-supplied error text has no authority. |
| `fallback-budget-exhausted` | held | The ceiling. An exhausted budget is not a policy verdict. |

Four properties follow, and each exists because its absence is a specific failure:

- **The prior lease must already be gone**, asked of the *capacity table* rather than of the key store, because a lease slot is exactly what a successor would double-book and the slot is released on every path that ends a key. While the prior key can still reach an upstream, a successor is a second live lease for one dispatch and both of them can spend.
- **A hop starts past the account that failed**, not merely "at the next eligible one" — `start_position = cited.fallback_position + 1`. A hop that could re-select the account whose terminal failure licensed it is not a fallback.
- **The boundary never widens.** The verdict returns a position and nothing else; the candidate list is recomputed from the same effective model by the same registry and every live filter still applies. An account refused at position 0 is refused just as hard at position 3.
- **A mismatched citation is refused rather than silently restarted.** Restarting at position 0 could re-select the very account being cited — a retry storm wearing a fallback's clothes.

`supersedes` is the same machinery with the advance switched off: it recovers a lost mint response at the *same* position after an acknowledged revoke, so it consumes no budget and needs no terminal evidence — the thing it recovers from is the *absence* of a response. A **renewal is neither**: `GatewayMintV2Request.with_new_attempt` clears any citation, because a renewal mints before it revokes and would otherwise present its own live lease to the revoke-then-remint check and turn every renewal into a refusal.

### D5: The administrative overlay IS its audit chain

`AccountAdminStore` has no snapshot file. `read()` folds the hash-linked chain (ADR-0139's `RoutingAuditLog`, reused verbatim rather than re-implemented — `route_shadow` already reuses it for a different chain), and `revision` is the chain's own length. **One mutation is one append**, so there is no window in which a state change exists without its audit record or a record exists without its change — the failure a two-file write would have needed ADR-0140's write-ahead journal to close. Mutations are rare, and an O(1) tail read of the head lets an unchanged chain be served from cache.

Two behaviours follow:

- **The chain is verified on every re-fold**, not merely before a mutation. A reader that trusted the chain it was about to fold would publish exactly the overlay an attacker edited into it, and this overlay's whole job is to say which accounts an operator withdrew. An unverifiable chain reports `SnapshotState.CORRUPT`, the mint **holds** every governed attempt with `account-state-unavailable`, and every further mutation is refused so a write cannot extend a chain nobody can trust.
- **A side effect happens inside the mutation.** `record_revocation` takes the revoke as a callable and runs it after the revision check and before the append: revoking first would let a stale request destroy leases and then be told 409, and appending first would record a revocation that had not happened.

Optimistic concurrency is the revision **in the body**, not an `If-Match` header — the design document asks for the header, and this follows ADR-0140's `PolicyMutation.expected_revision` instead so the whole routing control plane has one convention and one 409. Recorded as a deliberate divergence rather than left for a reader to notice.

**On actor provenance, honestly.** The gateway's authenticated boundary is a shared control token with no caller identity; the design's distinct read/mint/policy-admin scopes are not built. The recorded `actor` is supplied by the caller that already holds that token — HydraFlow's dashboard, which authenticates a real operator first — and the record carries `actor_authenticated_by: gateway-control-token` rather than presenting a caller-declared string as an authenticated identity. ADR-0138 §D5's precondition is met on the dashboard side: the two write routes are gated on `operator_identity.write_gate` and `authenticate_operator`, exactly like ADR-0140's policy mutation, and the actor the gateway records is the authenticated identity rather than a body field a browser controls.

## Non-goals — what this phase deliberately does not build

- **No HydraFlow-side fallback driver.** The protocol is complete and enforced at the gateway; nothing in `src/` yet *decides* to hop. The seam that would is a worker retry, and a retry today gets a fresh `dispatch_id`, so the lineage is gone before it could be cited. Carrying a dispatch across attempts is ADR-0137's worker-routing work (#11541/P5), and building half of it here would mean a driver with no lineage to drive.
- **No per-policy pool or per-policy fallback conditions** (D2). Recorded and inert, and #11544 owns them because they need the snapshot on the gateway side.
- **No weighted or least-active selection.** The design permits them "only after their fairness and recovery semantics are proven", and ordered selection is the one whose answer can be stated before the request.
- **No active health probing.** Passive evidence only. A background probe burns paid model calls to answer a question terminal rows already answer, and an unknown probe result would still have to be `unverified`.
- **No per-lane circuit finer than the account.** The circuit is keyed on the account, because rate limits and credit exhaustion are properties of a *credential*, not of a model. A per-model lane would fragment the evidence to a handful of requests each and make the threshold meaningless.
- **No durable capacity or circuit state.** Both are process-local; a restart forgets them (see Consequences).
- **No `forbid_direct_bypass` enforcement** — still recorded and inert; #11544 measures it.
- **No retirement of any legacy dial** (#11543/P6).

## Consequences

- **Capacity, circuit, and terminal evidence are process-local.** A gateway restart forgets every lease count and every open circuit, and an attempt citing a decision from before the restart *holds* rather than hopping — the safe direction, and the same trade ADR-0141 accepted for its attempt table. Because leases are also lost on restart (the key store is in-memory and fail-closed), the counts restart consistent with the keys they describe rather than drifting.
- **A governed mint now touches the filesystem, and it does so on the event loop.** `AccountAdminStore.read()` runs inside the mint's lock, so it is a `stat` plus a bounded tail read per attempt — one syscall in the default case, where the chain file does not exist at all. The fold is cached on the chain head, so a deployment that has never administered an account pays a failed `stat`. The write path takes a file lock with a ten-second timeout on the same loop; account mutations are operator-driven and rare, and putting them on a thread would buy nothing at this frequency. Both are named here rather than discovered under load.
- **A hop costs a lease and a revoke.** Bounded fallback is not free: each hop is a control-plane round trip and a new key. At `max_fallback_hops=1` the worst case for one dispatch is two leases, sequentially, never concurrently.
- **The default is inert and the proof is a regression test, not a claim.** No accounts file means one account per lane; one candidate means no hop has anywhere to go; `GATEWAY_MAX_FALLBACK_HOPS=0` refuses every hop outright.
- **ADR-0141's canary is untouched.** The enforcement bound is still one canonical repository × gateway transport, `canary_blast_radius` still enumerates it from the same matrix, and clearing `gateway_enforcement_canary_repo` still disarms on the next spawn. This phase changes which *account* a governed spawn lands on, never *whether* a spawn is governed. `tests/regressions/test_issue_11539_canary_off_is_byte_identical.py` passes unchanged, which is the check rather than the assertion.
- **`GatewayLedgerRow` still cannot join the credential-shaped-field sweep.** A #11653 review recorded it as "absent though it passes today"; it does not pass — it declares `input_tokens`, `output_tokens`, `cache_read_input_tokens` and `cache_creation_input_tokens`, and the sweep's marker set cannot tell a billing count from a credential. Listing it would have meant loosening the marker for all 27 models, trading a real guard for a nominal entry. It is left out with the reason recorded, and its *wire* projection is swept end to end already: a populated row is driven through `/control/v2/routes/recent` in the live-payload fixture. `GatewayIdentity` did pass and has been added.
- **The whole `GATEWAY_` namespace is now scrubbed from worker environments by prefix.** Strictly more scrubbing than before, and the reason is that a declared account's credential variable is operator-chosen and unenumerable. Any future non-secret `GATEWAY_*` variable a *worker* legitimately needs would have to be renamed out of the namespace.

## Alternatives considered

- **Let HydraFlow send the ordered pool with the mint**, since the policy that names it lives there. Rejected: the gateway cannot verify a pool came from a policy, so a caller sending a pool of one would pin its own account — caller-selected binding wearing a third name, and exactly what ADR-0141 AC1 forbids.
- **Let the caller declare the qualifying failure classes** (`fallback_on`) on the mint. Rejected for the same reason in a weaker form: it cannot fabricate the failure or reach a forbidden account, but it *can* widen which failures buy a hop, and "the gateway's own ledger is the only authority" is a cleaner rule than "the caller may widen the set within a ceiling."
- **Retry the paid request inside the proxy against the next account.** Rejected outright, and the design says it too: by the time a 429 is observable the request has already been made, and re-sending it is a second charge on a second account with no decision record between them.
- **Mint the successor first and revoke the old key after** (which is what lease *renewal* does). Rejected for fallback: renewal is the same account and the same spend, while a hop is a second billing identity. Mint-then-hope there means a window with two live leases for one dispatch, which is precisely the duplicate billing the v2 mint exists to prevent.
- **A separate snapshot file for administrative state, with a write-ahead journal like ADR-0140's.** Rejected as the wrong size: the state is a handful of enum values, mutated a handful of times in a deployment's life, and folding the chain removes the two-writer problem instead of solving it. The journal earns its complexity for a multi-policy snapshot; it does not here.
- **Treat every account as enabled when the audit chain will not verify**, so a tampered log cannot cause an outage. Rejected: it resurrects exactly the account an operator disabled, which is the one scenario the overlay exists for. Holding is an outage in the safe direction and it is loud.
- **Give capacity a default ceiling so every account is bounded.** Rejected: it would make an additive registry a throughput regression for every deployment that never asked for a pool, and a limit nobody chose is a limit nobody will diagnose.
