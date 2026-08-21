# Gateway accounts, active routing, and project policy control

**Status:** design proposal (2026-08-20). **Sequencing:** follows the README/site
alignment review and Fable scheduling design. This is the actuator phase already
reserved by `llm-gateway-session-tap.md`: the gateway sensor and ledger ship
first; account-aware routing becomes authoritative only after observation,
shadow comparison, and a project canary.

## Outcome

Add a dedicated Routing control surface where an operator can:

1. see which provider accounts are configured, enabled, degraded, leased, or
   actively serving a request, and why one is eligible for a specific route;
2. see the effective route for every repository/project and worker role;
3. inspect live and recent route decisions with a deterministic “why” trace;
4. create a rule such as “project X always uses z.ai models”;
5. map Fable-requested literal Opus/Sonnet families or provider-neutral
   capabilities to semantically compatible accounts and models;
6. preview, validate, version, audit, disable, and roll back policy without ever
   exposing a provider secret;
7. fail closed when no allowed route exists—never silently bypass the gateway.

The gateway becomes the routing authority for gateway-transited work. HydraFlow
still owns workflow roles, prompts, worktrees, and worker lifecycle; the gateway
owns which server-side account/model route satisfies a typed child intent.

A policy cannot honestly say “all project-X traffic” while some project-X
one-shot HTTP calls bypass the gateway. Until the OpenAI-compatible gateway face
exists, a provider-locked policy must declare its scope as agentic-only or make
unsupported direct faces a config error for that repository. The coverage gauge
remains the proof that no ungoverned spend was omitted.

## Current state and gaps

The v1 gateway is deliberately simple:

- `GatewaySettings.upstreams` is a dictionary keyed by provider binding, so it
  supports at most one Anthropic account and one z.ai-harness account;
- upstream secrets and base URLs are server-owned environment settings;
- the mint caller chooses `provider_binding` directly;
- the virtual key stores provider binding, repo identity, principal, capture
  policy, issue/session identity, and TTL;
- the proxy performs exactly one attempt against that immutable binding;
- the request ledger records repo, principal, requested/served model, provider,
  usage, latency, cost, and status;
- `/healthz` reports gateway telemetry health and configured provider names;
- `VirtualKeyStore.active_count` is total-only and private;
- no route policy, account alias, decision id/revision, in-flight registry,
  route explanation, or policy mutation API exists.

HydraFlow currently resolves routes at spawn time with this compatibility order:

```text
explicit non-Claude role provider > repo_provider > credit failover
```

The gateway fleet promotion runs before repository routing, Codex is excluded
from repository routing, gateway credit failover can still change the upstream
to z.ai, and some direct stream/one-shot paths do not pass through
`repo_provider`. A missing direct z.ai key also leaves a nominal z.ai override
on Claude. Consequently today's `repo_provider=zai` is a useful preference, not
an honest guarantee that every eligible project-X call uses z.ai.

The settings UI shows flat model/provider fields and a boolean “key detected”
badge for direct OpenAI-compatible backends. That badge proves only that an
environment variable is nonempty. It is not gateway account health or evidence
that traffic is using the account.

## Vocabulary: do not call everything “active”

Account-global facts and decision-context facts must not be collapsed into one
badge. Each account exposes these sanitized global facts:

| State | Meaning |
|---|---|
| `configured` | The gateway resolved a credential for the account at startup. |
| `enabled` / `draining` / `disabled` | The live administrative overlay permits new leases, only existing leases, or no traffic. |
| `available_capacity` | A sanitized lease-slot and request-slot summary, not a routing promise. |
| `leased` | At least one unexpired virtual key is bound to the account. |
| `in_flight` | At least one authenticated request is currently streaming through the account. |
| `observed` | A terminal ledger row used the account inside an explicit window and `as_of` time. |
| `degraded` | Passive request evidence crossed a threshold for a named request-face/model lane, with reason and retry/reset time. |
| `unverified` | Configured but no trustworthy success/failure evidence exists yet. |

`eligible` exists only inside a route explanation: it means this account can
satisfy this canonical repo, role, request face, and model requirement at this
policy revision. One account can be eligible for a balanced GLM worker and
ineligible for literal Opus at the same time. Overview therefore counts
configured/enabled/leased/in-flight accounts, never globally “eligible” ones.

The UI must present these facts independently. “Key configured” must never render as
“healthy,” and “healthy” must never render as “currently routing.” Account
balance or subscription quota is shown only if an authoritative provider API
supplies it; HydraFlow must not infer it from a credential or recent success.

## Architecture

```text
server-owned account config + secret references
                    |
             AccountRegistry
                    |
managed policy snapshot --> RouteResolver <-- live passive health/circuit state
                    |             |
                    |       RoutingDecisionLedger
                    v             |
            resolve-and-mint v2   |
                    |             |
            immutable virtual key |
                    |             |
              GatewayProxy -------+
                    |
          ActiveRouteRegistry + request ledger
                    |
           HydraFlow admin client
                    |
              Settings / Routing UI
```

The browser never calls the gateway control plane directly. HydraFlow's backend
holds the control token, calls the gateway with `trust_env=False`, enforces
repository scope, and returns only sanitized models to the UI.

## Account registry

### Server-owned account definition

Introduce a restart-required `GATEWAY_ACCOUNTS_FILE` with versioned,
non-secret account metadata. Secret values remain in environment/secret mounts;
the file contains only the name of a secret source.

```yaml
schema_version: 1
accounts:
  - id: zai-primary
    display_name: z.ai coding plan
    provider_binding: zai-harness
    base_url: https://api.z.ai/api/anthropic
    auth_style: bearer
    credential_env: GATEWAY_ACCOUNT_ZAI_PRIMARY_KEY
    credential_kind: coding-plan-api-key
    billing_kind: flat_rate
    lease_capacity: 4
    request_capacity: 8
    allowed_models: [glm-5.3]
    capabilities: [balanced, high-reasoning]
```

Rules:

- `id` is stable, non-secret, unique, and safe for ledgers/URLs.
- API responses may expose id, display name, provider, base origin, auth style,
  credential kind, capabilities, concurrency ceiling, and
  `credential_configured`; they never expose the credential,
  credential fingerprint, environment contents, or control token.
- Base URLs remain fixed validated origins with no userinfo/query/fragment.
- Account definitions are loaded atomically and validated before readiness.
- Credential/base-url changes require gateway restart. `billing_kind` and
  `cost_basis` distinguish metered actual spend from flat-rate/notional token
  estimates. The UI never presents notional cost as an account charge.
- Administrative account state is a separately persisted, audited live overlay
  (`enabled`, `draining`, `disabled`); it is not a restart-required file edit.
- Account definitions expose allowed concrete models and provider-neutral
  capabilities. The versioned policy/model catalog alone maps a requested
  literal family or capability class to a concrete model.
- The two legacy `GATEWAY_ANTHROPIC_*` and `GATEWAY_ZAI_HARNESS_*` pairs compile
  into deterministic `legacy-anthropic` / `legacy-zai-harness` accounts during
  migration; they are not a second runtime registry.

### Passive health and circuit state

Start with passive evidence from actual requests. Do not burn paid model calls
for background health checks by default.

Per account and request-face/model lane retain bounded non-secret state:

- last selected, request start, successful completion, error, and rate-limit
  timestamps;
- active lease and in-flight request counts;
- recent request/error counts, p95 latency, known spend, and model set;
- consecutive qualifying failures and circuit state;
- sanitized failure class (`credit_exhausted`, `rate_limited`, `unavailable`,
  or other), evidence authority, retry/reset time, and last state-change reason.

Lease/session admission and data-plane request admission are separate atomic
capacities. Resolve-and-mint reserves a lease slot before selecting an account;
the proxy independently enforces concurrent request slots. Reservation,
release, expiry, revoke, and crash recovery are tested as one lifecycle so a
burst of unused keys cannot oversubscribe an account before requests begin.

Provider-specific non-billable probes can be added behind adapters later. An
unknown probe result remains `unverified`, not healthy.

## Policy model

Policies match canonical spawn context and return one immutable route decision.

All APIs and persisted models use one typed `ModelRequirement` wire object:
`{kind: literal_family | capability | concrete_model, value: string}`. UI labels
may say Opus/Sonnet or balanced/high-reasoning, but policy matching, precedence,
mint, ledger, receipt, and tests never encode an ambiguous bare “tier.”

```yaml
id: project-x-zai
enabled: true
priority: 100
match:
  repo_ids: [acme/project-x]
  repo_classes: [client]
  roles: ['*']
  model_requirements: []  # omitted/empty means any
action:
  provider_lock: zai-harness
  forbid_direct_bypass: true
  account_pool: [zai-primary, zai-secondary]
  model:
    requirement_map:
      - requirement: {kind: capability, value: balanced}
        effective_model: glm-5.3
      - requirement: {kind: capability, value: high-reasoning}
        effective_model: glm-5.3
    allowed_patterns: ['glm-*']
  selection: ordered
  on_unavailable: hold
  fallback_on: [credit_exhausted, rate_limited, unavailable]
```

### Match fields

First version:

- exact canonical lowercase `owner/repo` identity;
- repository class;
- canonical `WorkerRole` from one shared catalog used by Classic runners,
  Fable, mint requests, explanations, ledgers, and receipts;
- requested model requirement: a literal family such as `claude-opus`, a
  provider-neutral capability such as `high-reasoning`, or a concrete model;
- optional model pattern and request face;
- enabled time window only if a clear operator need appears.

Carry canonical `owner/repo` separately from the path-safe runtime slug. The
current lossy slash-to-hyphen slug is never a policy identity: `a-b/c` and
`a/b-c` must remain distinct. Old ledger rows retain an explicit
`repo_identity_version=legacy-lossy` and cannot silently satisfy an exact-repo
policy join. Use exact canonical repository identities in v1. Add validated globs only after the
conflict/explanation model has real evidence. Do not start with issue-label
expressions, arbitrary code, regex, or prompt/body inspection. Those make
policies hard to explain and turn content into routing control input.

### Actions

- ordered account pool and an explicit provider-binding lock;
- optional fail-closed prohibition on direct/non-gateway faces;
- allowed model patterns;
- requested-requirement-to-effective-model mapping owned by the versioned
  policy/model catalog; account definitions only advertise capabilities;
- deterministic account selection (`ordered` first; weighted/least-active only
  after their fairness and recovery semantics are proven);
- allowed fallback conditions and ordered fallback targets;
- typed `route_held` or `route_rejected` when no route is eligible; the gateway
  never blocks waiting, and the IssueDriver owns delay/requeue using the
  bounded reason and optional retry time;
- optional per-request/session budget and concurrency ceiling in a later phase;
- body-capture policy remains governed independently by repo class and the
  server allowlist.

“Project X always uses z.ai” means `provider_lock=zai-harness`. If Fable asks for a
provider-neutral high-reasoning worker, the policy may map it to an approved
z.ai model. A literal `claude-opus` requirement cannot map to GLM; the resolver
rejects or holds it rather than silently escaping to Anthropic or mislabeling
the model.
With `forbid_direct_bypass=true`, config/spawn validation also rejects any
project-X LLM surface the gateway cannot govern rather than letting the request
disappear from the policy domain.

## Precedence and conflict rules

System safety constraints always win. Managed policy deny/hold actions compete
at the same defined specificity as selection actions; a broad global hold does
not defeat a more specific exact-project route unless it is explicitly marked
as a system safety rule. Managed policy then outranks compatibility defaults so
a project policy can actually mean “always.”

1. gateway readiness, credential boundary, repo-class capture policy, enforced
   direct-face boundary, and disabled/circuit-open accounts;
2. exact repository + exact role + exact model-requirement policy;
3. exact repository + exact role policy;
4. exact repository wildcard-role policy;
5. repository-class + role policy;
6. repository-class default policy;
7. global role/model-requirement policy;
8. global default;
9. compiled legacy role defaults, repo default, and credit-failover behavior
   during migration only.

Within one precedence level, higher numeric priority wins. Two enabled policies
with the same specificity and priority that resolve differently are invalid;
the store rejects the update instead of relying on insertion order. Exact
canonical repository identity matches outrank globs; overlapping equally
specific globs are a validation error.

The resolver returns the entire ordered trace: policies considered, match/no
match reason, precedence tuple, rejected accounts/models, chosen account/model,
and fallback eligibility. The trace is sanitized and bounded.

## No silent or mid-session rerouting

One route is fixed when the virtual key is minted:

- account id, provider binding, effective model, policy id/revision, decision
  id, and fallback position are immutable key identity;
- HydraFlow receives the effective model and rewrites the worker command before
  launch, so requested requirement/model and effective model are explicit;
- a policy edit affects only new keys;
- the proxy still performs one upstream attempt and forwards errors verbatim;
- it never retries a paid request against another account;
- after a qualifying 429/credit/unavailable outcome, a *new worker attempt or
  lease* may resolve the next allowed route and produces a new decision id, but
  only when it cites a prior decision whose authoritative terminal request row
  proves that qualifying outcome;
- revoking active leases after a policy change is a separate explicit operator
  action with blast-radius confirmation, not an automatic side effect.

The key is also bound to the effective model. A request for a different model
must fail closed before any upstream bytes rather than consuming the same
account under an unapproved model. P3 is gated on a compatibility probe that
enumerates every Claude CLI request face and auxiliary call. For bounded JSON
message faces, preflight validates content type and size, rejects duplicate or
missing model keys, parses the complete body, and compares its model with the
immutable decision before constructing the upstream request. Unsupported,
streaming-body, or non-message faces are explicitly classified and rejected for
a governed repository until an equally strong binding exists. Merely observing
a model after bytes reached upstream is not enforcement, and the proxy never
silently rewrites the body.

This preserves the gateway's transparency and avoids duplicate billing.

## Route-aware mint contract

Keep `/control/v1/keys` only during observation/shadow migration. It cannot
coexist unrestricted with an enforced repository because the current shared
control token has no caller identity. Before P3, either disable v1 mint in
enforced mode, give compatibility callers separately scoped credentials with
repo/principal allowlists, or make v1 structurally reject every governed repo.

Add a v2 resolve-and-mint request whose authoritative fields are identity and
intent, not caller-selected provider credentials:

```text
dispatch_id / mint_attempt_id
retry_of_decision_id or supersedes_decision_id (optional, mutually exclusive)
principal / spawn / parent-driver lineage
canonical lowercase owner/repo, path-safe runtime slug, identity version, class
canonical WorkerRole
requested model requirement and requested concrete model, if any
capture request and TTL
expected policy revision (required for Fable; optional only for declared legacy callers)
```

The response includes the existing one-time token plus a sanitized decision:

```text
decision_id
outcome = selected | held | rejected
policy_id / policy_revision
account_id / provider_binding (selected only)
requested requirement/model / effective model (effective only when selected)
matched scope and reason codes
fallback position / retry_at
```

Every resolve attempt appends exactly one decision, including held, rejected,
and stale-revision outcomes. Only `selected` decisions reserve capacity and mint
a key; each terminal request row references that decision. The
`GatewayIdentity`, key store, routing-decision ledger, request ledger, and
telemetry all carry the lineage.

`dispatch_id` identifies one logical worker dispatch and remains stable across
its bounded fallback or recovery attempts. `mint_attempt_id` identifies one
resolve/key-issuance attempt and is the HTTP idempotency key: retries reuse it;
a new key always requires a new value. The store persists a canonical request
fingerprint. Reuse with different identity/intent returns 409.

One atomic transaction records the attempt, decision, capacity reservation,
key id/hash, and policy/account revisions, or records none of them. Held and
rejected results replay their sanitized decision. For a selected result, the
raw token exists only in the original response path and is never persisted; a
retry of the same `mint_attempt_id` returns typed `mint_outcome_unknown` with
decision/key ids but no token and creates nothing. The client must receive an
acknowledged targeted revoke, then send a new attempt with
`supersedes_decision_id`. The gateway validates that the old decision belongs
to the same dispatch/context and is revoked before reserving again.

Normal fallback uses `retry_of_decision_id`. The gateway verifies matching
dispatch/context plus its own terminal request ledger and advances exactly one
position only for a policy-approved failure class. Caller-supplied error text
has no authority. Without verified retry lineage, resolution starts at the
current policy's first eligible route; it cannot claim deterministic fallback
advancement. No protocol path replays a token or silently accumulates a lease.

## Detecting active routing

Add an ephemeral `ActiveRouteRegistry` with strict lifecycle ownership:

- `leased`: route-bound key minted and not revoked/expired;
- `in_flight`: proxy accepted an authenticated request and has not finalized;
- `recent`: terminal request ledger row inside the selected window.

Register after identity resolution and remove in `finally` across normal,
upstream error, cancellation, client abort, telemetry failure, and shutdown.
Expose counts and sanitized route descriptors, never tokens, headers, prompts,
body paths, or raw request ids where correlation is unnecessary.

The UI can therefore distinguish:

- “configured but idle” account;
- “2 leases, no request yet”;
- “1 request streaming for project X / implementer / glm-5.3”;
- “last used 12 minutes ago, completed 200”;
- “the route was held because every account was unavailable” from a durable
  decision record, never from an active lease.

Held and rejected decisions appear in recent decisions/audit, but never in
leased or in-flight counts and never as request rows. One key may have several
concurrent requests, so the registry keys request activity by attempt while
aggregating leases separately.

## Control and dashboard APIs

Gateway control plane (authenticated before parsing, size-bounded like v1):

- `GET /control/v2/accounts` — sanitized status/capabilities/counters;
- `PATCH /control/v2/accounts/{id}/state` — audited enable/drain/disable with
  required `If-Match`/expected account-state revision;
- `POST /control/v2/accounts/{id}/revoke-leases` — explicit blast-radius action;
- `GET /control/v2/routes/active` — leases and in-flight routes;
- `GET /control/v2/routes/recent` — bounded decision/request summaries;
- `GET /control/v2/decisions/{decision_id}` — the durable, original bounded
  trace for selected, held, or rejected resolution;
- `GET /control/v2/policies` — current snapshot and revision;
- `POST /control/v2/routes/explain` — pure dry run, no key or side effect;
- `POST /control/v2/routes/explain-batch` — one resolver snapshot for a
  context matrix and optional candidate policy snapshot; the response embeds
  each bounded trace and pins policy/account-health revisions, so drill-down
  never re-resolves against newer state;
- `POST /control/v2/policies/validate` — conflicts and route reachability;
- `POST /control/v2/policies` — create with expected snapshot revision;
- `PATCH /control/v2/policies/{id}` — versioned update/enable/disable;
- `POST /control/v2/policies/rollback` — target and expected revisions,
  validated against the current account registry, creating a new revision;
- `GET /control/v2/policies/audit` — append-only mutation history;
- `GET /control/v2/admin/audit` — unified account-state, lease-revocation, and
  policy-admin mutation history;
- `POST /control/v2/keys` — resolve-and-mint.
- `DELETE /control/v2/decisions/{decision_id}/key` — targeted, idempotent,
  acknowledged revoke for normal cleanup and lost-response recovery.

Use optimistic concurrency: every policy snapshot and administrative-account
overlay has a monotonically increasing revision/ETag. Stale updates return 409
with no partial write, so an old browser cannot undo an emergency disable. The
account-state mutation and its audit append commit in the same recovery
transaction described below. Prefer
soft disable and a new revision over destructive deletion. Policy snapshot,
mutation intent, and audit head use a write-ahead transaction/journal: recovery
either completes both the atomic snapshot replace and hash-chained audit append
or leaves the prior revision authoritative. Rollback is a new audited revision,
never restores secrets, and cannot partially restore a multi-policy snapshot.
Every mutation records authenticated actor/source, prior/new revision,
normalized diff, validation result, and timestamp—never secrets.

Use distinct read, mint, and policy-admin control credentials/scopes. Policy
writes require an authenticated operator identity at the HydraFlow backend and
are disabled when the dashboard is exposed beyond loopback until that
authorization exists. Audit actor provenance comes from this authenticated
boundary, not a caller-supplied JSON field.

HydraFlow dashboard routes proxy these operations consistently under
`/api/gateway/...`. The browser never receives a gateway control credential.
Routing hooks use the operator console's canonical selection directly:
`repo=<owner/repo>` for a repository and `repo=__all__` for aggregate reads.
They do not inherit the independent `HydraFlowContext.selectedRepoSlug` default.
Repository-policy writes reject `repo=__all__` and reject any policy body whose
scope differs from the authorized URL scope. A repo view shows inherited
exact-repo, class, and global policies, but edits only exact-repo policies.
Aggregate mode is read-only. A distinct host-admin mode and authorization scope
owns account state, lease revocation, and class/global policies; those endpoints
do not masquerade as aggregate repo writes and render read-only when host-admin
authorization is absent.

## UI design: Settings > Routing

Nested, versioned policies should not be squeezed into the generic flat
`RuntimeSettingsPanel`. Reuse shared operator primitives, error handling,
settings shell, and the one canonical operator repo selector; do not reuse its
private legacy-theme row functions. Add a dedicated Routing workspace with a
full-width `?mode=routing` operator mode and five URL-addressable views via
`routingView=accounts|effective|policies|live|audit`. Routing is global and
idle-exempt: it bypasses the portfolio-detail/`IdleState` gate and retains the
full-width detail grid in aggregate mode. Add `routing` to both `MODES` and
`VALID_MODES`. The Settings drawer gets a compact third Routing tab that shows
status and deep-links to this workspace; policy editing remains full-width.
Add a compact Routing Summary to the vitals rail; clicking it opens the full
mode. A separately authorized host-admin submode exposes global account and
class/global policy controls; ordinary repo and aggregate views render those
controls read-only.

### 1. Overview

- gateway ready/degraded/unreachable;
- active policy revision and last successful refresh;
- configured/enabled/leased/in-flight account counts; route-specific
  eligibility appears only in an explanation;
- active leases, in-flight requests, recent requests/errors/spend;
- coverage gauge and direct-bypass warning;
- clear degraded/source-unavailable copy.

### 2. Accounts

Cards/table with account display name/id, provider binding, credential configured,
administrative/circuit/capacity state, supported capabilities/models, active leases,
in-flight requests, last success/error, recent error rate/latency and
actual-versus-notional cost basis. All time-derived facts include their window
and `as_of`. No
secret input field in v1. Account creation/credential rotation remains a
server-deployment operation; the UI explains the required restart.

### 3. Effective routes

A repository-by-worker-role matrix derived in one batch from HydraFlow's
supervised repository registry, not merely policies or observed ledger rows.
The response pins one `policy_revision`, completeness/staleness, and a bounded
explanation reference per cell. Each cell shows requested requirement, effective
model, provider/account, matched policy, and fallback state. Separate indicators
show leased, in-flight, and observed-within-window with `as_of`; there is no
ambiguous “live” badge. Selecting a cell opens the snapshot-pinned explanation
trace already returned by the batch. A toggle distinguishes configured
resolution from recent observed traffic.

### 4. Policy builder

- select repository/class, roles, and model requirements;
- choose provider lock, ordered account pool, requirement/model mapping, unavailable
  behavior, and allowed fallbacks;
- continuously validate conflicts and unavailable model/account combinations;
- show a revision-consistent batch dry-run matrix of affected routes and a
  before/after diff using an optional candidate snapshot;
- require explicit confirmation when an edit changes active-repo routing;
- save with the revision originally loaded; surface 409 conflicts for reload.

### 5. Live routes and audit

Live leases/in-flight table plus bounded recent terminal routes. Columns:
repository, issue/role, Fable parent lineage where applicable, requested requirement,
effective/served model, account, policy revision, age/latency, status, and cost.
Held/rejected attempts appear as recent decisions with no key/request row. An
audit timeline shows policy revisions and rollback targets separately from
traffic. Rollback posts a target revision plus the revision originally loaded;
a stale rollback returns 409 and no partial mutation.

## Fable director integration

The Fable scheduling design asks the worker broker for a role and model
requirement, for example
`implementer + {kind: capability, value: balanced}` or
`reviewer + {kind: literal_family, value: claude-opus}`. The broker sends that typed intent to the
route resolver. Fable may inspect the sanitized explanation and availability,
but it cannot choose a raw account/model outside policy.

This permits one director to invoke:

- the Fable coordinator itself through a separately named account that supports
  `claude-fable-5`;
- provider-neutral balanced planner and implementer workers on z.ai for
  project X;
- an independent Opus reviewer on a separately approved Anthropic account;
- or a provider-locked z.ai high-reasoning reviewer if project policy forbids any
  Anthropic route.

Every child gets a distinct dispatch id, decision, virtual key, account binding,
and receipt. Fable dispatches pin `expected_policy_revision`; a stale revision
returns a deterministic refresh-required result rather than selecting from a
different snapshot.
Native Claude Task children that inherit the parent's one account cannot satisfy
mixed-account policy; those remain limited to same-account experiments.

OAuth/subscription identities are not silently treated as gateway accounts.
The present gateway has no authenticated attribution side channel for them.
Expose them only after that boundary exists; until then the Accounts view covers
gateway-owned API/coding-plan credentials and labels subscription visibility as
external/unmanaged rather than guessing from a local auth directory. A Fable
parent using a Claude subscription is likewise external/unmanaged; a named
Fable account is possible only when the parent uses a gateway-owned API or
coding-plan credential.

## Failure and security behavior

| Failure | Required behavior |
|---|---|
| Account secret missing | Account is `configured=false`, never eligible; gateway readiness fails if no usable account remains. |
| Policy targets unknown/incompatible account/model | Reject policy create/update; existing snapshot remains active. |
| No eligible route | Hold or fail closed per matched policy; never fall back to a direct worker credential. |
| Policy file corrupt or audit verification fails | Reject new route mints and report degraded readiness; do not synthesize defaults. |
| Gateway control unreachable | Dashboard becomes read-only/unavailable; workers fail closed when gateway was selected. |
| Health unknown | Show unverified; apply the explicit policy, not a fabricated healthy state. |
| Rate/credit/upstream error | Pass through and ledger it; update passive state; only a new decision can choose fallback. |
| Duplicate dispatch/mint retry | Return the one durable decision or require revoke-before-remint; never create a second hidden lease. |
| Lease or request capacity exhausted | Return typed held/rejected decision with lane, reason, and optional retry time; never block in the gateway. |
| Concurrent policy edit | 409 on stale revision, no lost update. |
| Policy changes with active keys | Existing immutable decisions continue; UI shows old revision until revoke/expiry. |
| Ledger/active registry unavailable | Gateway readiness degrades/fails closed under existing telemetry rules; UI never claims a complete route view. |
| Secret in log/API/model | Schema and logging tests fail; account APIs expose booleans and aliases only. |

Policy writes are control-plane operations. Authenticate before body parsing,
enforce strict request limits, disable access-query logging, reject unknown
fields, validate paths/origins, and never accept credential values through the
general settings API.

## Delivery sequence

### P0 — read-only account and route visibility

- Compile current single upstreams into account identities.
- Add sanitized account status, grouped active lease counts, in-flight registry,
  recent-route read model, and HydraFlow proxy client/routes.
- Add Accounts, Effective Routes (observed), and Live Routes read-only UI.
- No routing behavior changes.
- Introduce canonical `owner/repo`, shared `WorkerRole`, request-face, model
  requirement, billing-kind, and account/lane health types before matching.

### P1 — pure policy core and explanation

- Add typed account/policy/decision models and pure deterministic resolver.
- Add atomic versioned policy snapshot, hash-chained audit, validation, and
  explain/dry-run endpoints.
- Compile current role/repo/failover config into legacy compatibility entries.
- Shadow every current spawn and compare proposed versus actual route.
- Add read/mint/admin authorization scopes and keep writes loopback-disabled
  until operator identity is trustworthy.

### P2 — policy UI and shadow burn-in

- Add policy builder, conflict validation, before/after route matrix, revision
  concurrency, audit, and rollback-to-new-revision.
- Keep legacy routing authoritative while measuring disagreements and gaps.
- Establish source completeness and zero-secret UI evidence.

### P3 — resolve-and-mint canary

- Add v2 route-aware mint and immutable account/policy lineage.
- Add dispatch idempotency, atomic lease reservation, strict pre-upstream model
  binding, and typed held/rejected decision evidence.
- HydraFlow rewrites the worker command to the returned effective model before
  spawn.
- Enable one exact repository policy such as project X -> z.ai.
- Label the first canary agentic-only unless unsupported one-shot faces are
  rejected for that repo; do not market it as an all-traffic guarantee yet.
- Disable or cryptographically scope v1 mint away from governed repositories;
  a declaration alone is not an authorization boundary.

### P4 — multi-account pools and bounded fallback

- Support multiple accounts per provider, passive health/circuit state, ordered
  selection, and allowed new-attempt fallback.
- Add audited enable/drain/disable and explicit revoke-leases actions, with
  separate lease and in-flight request capacity.
- Prove no mid-request retry, no session rewrite, and no duplicate billing.

### P5 — Fable worker routing

- Carry driver/parent lineage and literal-family/provider-neutral model
  requirement through the broker,
  mint decision, active registry, ledger, and worker receipt.
- Prove mixed provider/account children from one Fable issue director while
  keeping the parent credential-minimal.

### P6 — retire parallel routing dials

- After enforced policy parity, migrate supported legacy fields into generated
  baseline policies and make the resolver the only spawn-routing decision seam.
- Remove hand-maintained role/repo/failover precedence paths only after config,
  MockWorld, sandbox, and rollback compatibility are proven.
- Add the OpenAI-compatible gateway face or fail closed on those direct
  one-shot providers for any repository whose policy forbids bypass; require
  the coverage tripwire to prove the final guarantee.

## Likely implementation surfaces

Gateway core:

- `src/hydraflow_gateway/settings.py`, `models.py`, `keys.py`, `app.py`,
  `proxy.py`, `ledger.py`
- new focused `accounts.py`, `routing_policy.py`, `routing_store.py`,
  `active_routes.py`, and `routing_audit.py`
- `gateway/README.md` and deployment/compose account-secret wiring

HydraFlow routing/client:

- `src/runner_utils.py`, `repo_backend.py`, `credit_failover.py`
- `src/base_runner.py`, `src/runners/base_subprocess_runner.py`
- new gateway admin client and effective-route read models
- `src/config.py`, `settings_registry.py`, `repo_store.py`
- dashboard control/diagnostics routes and models
- Fable director broker/lineage seams from the scheduling proposal

UI:

- `src/ui/src/components/SystemPanel.jsx`
- `src/ui/src/operator/OperatorConsole.jsx`, `useOperatorSelection.js`,
  `SettingsDrawer.jsx`, `SettingsSummary.jsx`, and `RepoOverview.jsx`
- `RuntimeSettingsPanel.jsx` for compact links/status, not policy editing
- new `RoutingMode`, `RoutingSummary`, Accounts, Active Routes, Effective
  Routes, Policies, Explanation, Decisions, and Audit components plus pure view
  models/hooks
- one operator-selection-derived repo scope for routing hooks; explicit
  `__all__` aggregate reads and aggregate-write rejection
- operator Settings drawer/summary and Factory Cost gateway gauge integration

Testing/fakes:

- gateway account/resolver/store/audit/active-route/API/ledger tests;
- canonical-repo collision, shared WorkerRole, model-catalog, v1 scope,
  dispatch-idempotency, capacity reservation, and strict model-preflight tests;
- same-attempt replay/fingerprint conflict, selected-response loss followed by
  targeted revoke/remint, server-verified fallback lineage, stale account-state
  revision, and atomic decision/lease/key failure-injection tests;
- config, spawn routing, BaseRunner/BaseSubprocessRunner, repo, failover tests;
- dashboard API and UI component/view-model tests, including exact URL repo
  scoping, abort/stale response behavior, idle/aggregate routing layout,
  `routingView` round-tripping, revision-consistent/pinned batch traces, scope
  mismatch, host-admin/read-only rendering, account audit retrieval, and stale
  rollback;
- operator no-inline-style ratchet coverage and repo-aware
  `GatewayCoverageGauge` wiring using the selected scope key;
- MockWorld fake account/policy gateway and stateful route assertions;
- Docker sandbox scenario for account isolation, policy edit/explain, one real
  routed worker, active/recent UI, and secret absence;
- architecture/fake parity, settings-schema, path-filter, coverage, and security
  ratchets.

## Acceptance evidence

- Accounts screen distinguishes configured, administrative/capacity state,
  leased, in-flight, observed, degraded, and unverified without leaking any
  secret; eligibility appears only for a complete route context.
- An operator can explain any effective route before spawning and any observed
  route afterward using the exact policy/account/model revision.
- A project-X policy deterministically routes all selected roles to z.ai models;
  provider-neutral high-reasoning requests map explicitly, while incompatible
  literal Opus requests fail/hold without Anthropic escape.
- Changing a policy creates an auditable revision, affects only new leases, and
  rejects stale concurrent edits.
- One Fable issue director can request Opus/Sonnet workers and receive distinct
  policy-approved child routes and identities.
- Missing/corrupt policy evidence, unavailable accounts, gateway failure, and
  telemetry loss never present a false healthy/active state or cause direct
  credential fallback.
- Exactly one decision exists per resolve attempt; a selected decision has at
  most one key, while held/rejected decisions have none. Exactly one request
  row exists per authenticated gateway attempt; joins and active lifecycle
  survive concurrent use, cancellation, expiry, telemetry failure, and
  shutdown.
- A model mismatch, unsupported request face, or governed v1 mint sends zero
  bytes upstream.
- Policy snapshot and audit recover to one coherent revision after a crash;
  rollback creates a new revision and stale rollback is rejected.
- Classic legacy routing remains behaviorally identical until the explicit
  enforcement canary, and rollback to the prior policy revision is proven.

## Final ruling

Build account visibility and route explanation first, policy shadow second, and
enforcement third. Make “project X uses z.ai” a server-owned, versioned,
provider-locked rule whose decision is stamped onto every child key and ledger
row. Let Fable request literal Opus/Sonnet families or provider-neutral
capabilities; let the gateway policy choose only a semantically compatible
approved account and model. No secret, route, or merge authority belongs inside
the parent conversation.
