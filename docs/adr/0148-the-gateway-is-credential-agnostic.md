# ADR-0148: The gateway is credential-agnostic

- **Status:** Accepted
- **Date:** 2026-09-03
- **Enforcement:** enforced
- **Binds:** factory
- **Extends:** [ADR-0147](0147-the-gateway-is-the-only-path-for-llm-spawns.md) (which made the gateway the only path), [ADR-0142](0142-multi-account-pools-and-bounded-fallback.md) (the account pool this lane joins)
- **Related:** [ADR-0085](0085-secrets-never-persist-in-audit-stream.md) (why a credential is validated before it reaches a header), [ADR-0138](0138-gateway-account-identity-and-sanitized-route-visibility.md) (the data plane that swaps the credential)

**Enforced by:**
- pytest:tests/test_gateway_oauth_passthrough.py::TestTheOAuthHeadersAreBuilt::test_a_clients_own_betas_survive
- pytest:tests/test_gateway_oauth_passthrough.py::TestAProxiedRequestOnTheSubscriptionLane::test_the_upstream_gets_the_subscription_token
- pytest:tests/test_gateway_oauth_passthrough.py::TestAllThreeCredentialsCanShareOnePool::test_the_subscription_account_needs_no_environment_secret
- pytest:tests/test_gateway_subscription_credential.py::TestTheSource::test_a_stale_token_with_no_refresh_command_fails_closed

## Context

ADR-0147 routed every role dial through the gateway so the gateway ledger could
be the factory's one cost and attribution record. It shipped with an unstated
consequence: the gateway held exactly one static credential per upstream, and
the Anthropic upstream was pinned to `x-api-key`. "Everything through one
ledger" therefore *required buying metered API access*, and the operator's
existing Claude subscription could not reach the proxy at all.

That turned a telemetry decision into a billing decision. The live deployment
had no Anthropic key of any kind, so ADR-0147 as written could not be run: the
mint fails closed, and a stopped factory is worse than a partial ledger.

The rejected alternative was to leave routing alone and fix the *reader*
instead — the spawn-side `inferences.jsonl` already records role, issue, PR,
session, model, tokens and an estimated cost for subscription spawns, and the
reason it does not look like one place is that `_cost_rollups` loads a single
`cost_inferences_path` while the history spans two repo slugs. That remains
true and worth doing. It is not what this ADR decides, because it leaves two
records rather than one, and no per-spawn credential lease.

## Decision

**A gateway upstream declares how it authenticates, not which credential kind
the gateway supports.** Three lanes now coexist:

| Lane | `auth_style` | Credential | Billing |
|---|---|---|---|
| Claude subscription | `oauth-bearer` | OAuth token, read per request | `flat_rate` |
| Claude API | `x-api-key` | static key from env | `metered` |
| z.ai harness | `bearer` | static key from env | `metered` |

`oauth-bearer` is a distinct style rather than a flag on the existing bearer
path, because two things differ and both break if they share a branch: an
OAuth token to Anthropic is rejected without `anthropic-beta:
oauth-2025-04-20`, and it **expires** — so it cannot be an `UpstreamSettings`
field, which is read once at boot.

### The client's betas are merged, never replaced

The Claude CLI sends its own `anthropic-beta` values. Appending a second header
or overwriting the client's would silently disable whichever features the
caller asked for, so the OAuth flag is merged into one comma-joined,
de-duplicated header.

### All three are accounts, so fallback can hop between them

`GATEWAY_ANTHROPIC_AUTH_MODE` selects one credential for the env-level
Anthropic upstream, because both would occupy the same `ProviderBinding`
slot — that switch alone gives no sub-to-key fallback. Bounded fallback lives
in ADR-0142's account pool, and `load_account_pool` built every account with a
static secret from `credential_env`, so a subscription account could not be
declared. It can now: `auth_style: oauth-bearer` with no `credential_env`, and
`GatewayAccount` requires exactly one credential source rather than silently
dropping an account whose secret is absent.

This is what makes "subscription first, metered key second, z.ai third" a
configuration rather than a code change.

### `AccountBillingKind` gets its first consumer

The ledger row now records `billing_kind`. Pricing a flat-rate request the same
way as a metered one and summing both as dollars overstates spend — and the
point of one ledger was to stop guessing at cost. `AccountBillingKind`
(`metered` / `flat_rate`) already existed in the domain with exactly this
meaning and **no reader**; this is it, rather than a synonym (ADR-0053).

### The refresh command is operator-supplied

Anthropic's OAuth token endpoint and client id are vendor internals this repo
has not verified. ADR-0146 shipped one asserted-but-unchecked vendor capability
("Bugsink files GitHub issues itself" — it does not) and the correction cost a
follow-up section. So the refresh *mechanism* is implemented and tested — read,
detect staleness against a skew, run the configured command once, re-read, fail
closed — and the one value that would have to be guessed is configuration:
`GATEWAY_ANTHROPIC_OAUTH_REFRESH_COMMAND`.

Consequences of that choice, stated plainly: with no refresh command the lane
works until the token expires and then fails closed with a message naming the
remedy. It does not silently serve a dead token, and it does not retry the
refresh in a loop.

## Consequences

**Good.** One ledger covers subscription and metered traffic, so the cost
question has one answer without a new spend line. The factory can run ADR-0147
on credentials the operator already has. Fallback across credential *kinds*
becomes expressible.

**Costs.** The gateway now reads a credential store, which is a new class of
dependency for it: on macOS that is the login keychain, which is host-only —
a containerised gateway cannot reach it. A token is validated for newlines and
non-ASCII before it reaches a header, because a store returning
`tok\r\nx-evil: 1` would otherwise be a header-injection primitive.

**Risk accepted, explicitly.** Routing a Claude subscription credential through
a long-running local proxy that serves automated spawns is not what a personal
subscription is provisioned for, and Anthropic could refuse it at any time
(request shape, token binding, or terms enforcement). The operator was told
this before it was built and chose it knowingly. The rollback is one
variable: `GATEWAY_ANTHROPIC_AUTH_MODE=api_key`, or a dial back to `claude`.

**What this does not do.** It does not implement the OAuth refresh exchange, it
does not consolidate the historical `inferences.jsonl` ledgers, and it does not
make a host-mode gateway spawn *provable* — ADR-0147's isolation caveat stands
unchanged.
