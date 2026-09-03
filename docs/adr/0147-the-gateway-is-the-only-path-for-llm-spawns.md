# ADR-0147: The gateway is the only path for LLM spawns

**Status:** Accepted
**Date:** 2026-09-03
**Enforcement:** enforced
**Enforced by:**
- pytest:tests/architecture/test_every_dial_routes_through_the_gateway.py::test_the_dial_defaults_to_the_gateway
- pytest:tests/architecture/test_every_dial_routes_through_the_gateway.py::test_the_capable_set_covers_every_dial
- pytest:tests/architecture/test_every_dial_routes_through_the_gateway.py::test_the_dial_keeps_a_direct_escape_hatch
**Extends:** [ADR-0141](0141-bounded-reversible-routing-enforcement-canary.md) (the bounded canary this graduates), [ADR-0021](0021-persistence-architecture-and-data-layout.md) (the ledger's repo-scoped home)
**Related:** #11992 (the governed-repo config gate), #11987 (the architecture gate), #11999 (the runtime gauge)

## Context

An audit of cost telemetry on 2026-09-02 found the spend record almost entirely
blind, for a reason nobody had noticed because each half looked healthy on its
own.

**The gateway ledger is the only surface with per-spawn attribution.** One row
carries `principal` — `{kind, id, spawn_id, session_id, issue_number,
pr_number}` — plus `repo_slug`, `repo_class`, `upstream_provider`,
`model_requested`, `model_served`, tokens and `cost_usd`. It answers "what did
this role spend on that issue" for any provider, in one schema.

**Almost nothing goes through it.** The ledger held 908 rows spanning two days,
2026-08-20 to 08-21, every one `upstream_provider: zai-harness`, and nothing had
written to it in the two weeks since. Meanwhile the gateway process was
*running*. Every `*_provider` dial defaults to `claude`, which spawns the CLI
directly and never transits the proxy, so the ledger recorded the one lane
nobody was using.

The spawn-side store (`inferences.jsonl`, ADR-0021 D2) does record Claude work,
but it is repo-scoped and the slug moved twice over the repo's life — a
pre-scoping era, `T-rav-hydraflow`, and `hydraflow` when
`HYDRAFLOW_GITHUB_REPO` is unset. Every reader loads exactly one
`config.cost_inferences_path`, so roughly $6.4k of recorded history is
invisible to every tool that asks about cost. Two partial records, neither
complete, is the state this decision ends.

## Decision

**Every LLM spawn transits the gateway. The gateway ledger is the cost and
attribution record of the factory.**

The mechanism exists and is not new: `gateway_fleet_ratchet_enabled` rewrites a
spawn whose provider resolves to `claude` into a `gateway` spawn at
`base_runner`. It is the only lever that reaches everything — **20 of 24
`BaseRunner` subclasses declare no `PROVIDER_FIELD`**, so `_resolve_provider`
returns a hardcoded `"claude"` and no `*_provider` dial can move them. Flipping
the fourteen dials is therefore both redundant (the ratchet catches them) and
insufficient (it misses the twenty). The ratchet is the decision; the dials stay
as the per-role escape hatch.

### The dials are the lever; the ratchet is not required

Every one of the fourteen `*_provider` dials now defaults to `gateway`, and
`GATEWAY_CAPABLE_PROVIDER_FIELDS` — the single tuple the ratchet, the schema
tests and provider validation all consume — was widened to cover all fourteen
so the two halves cannot disagree about what "everything" means.
`maintenance_provider` mattered most: four caretaker roles inherit it at their
lightweight seam, so leaving it direct routed those four around the gateway no
matter what the named dials said.

**This needs no docker and no ratchet.** An earlier draft of this ADR led with
`execution_mode="docker"`, having conflated two separate things: the docker
requirement is a validator on `gateway_fleet_ratchet_enabled`, not on dials. A
config with all fourteen dials on `gateway` loads and runs in host mode. Docker
buys the last mile, not the first.

### What the dials do not reach

`_resolve_provider` returns a hardcoded `"claude"` for every `BaseRunner`
subclass that declares no `PROVIDER_FIELD` — bug_reproducer, hitl, research,
discover, shape, plan_reviewer, diagnostic. No dial moves them, and the fleet
ratchet is the only thing that does.

That ratchet requires `execution_mode="docker"`, and the reason is not
ceremony: on the host an agent CLI reads provider OAuth/keychain state **even
when its process environment is scrubbed**, so a rewritten provider would
record a gateway spawn that never transited the gateway. `docker_extra_mounts`
is forbidden for the same reason — a host mount re-exposes `.env` files and
credential homes inside an otherwise isolated worker.

So the remaining roles stay direct until an operator accepts docker execution.
That is a deliberate stopping point, not an oversight: a ledger that is
complete for the roles that spend, and honest about the ones it does not cover,
beats a ratchet that reports coverage isolation cannot back.

### Deployment sequence

One precondition is operator action, and it is the only thing standing between
this decision and a working ledger:

| Precondition | Why it is not optional |
|---|---|
| `GATEWAY_ANTHROPIC_BASE_URL` + `GATEWAY_ANTHROPIC_API_KEY` in the **gateway process** environment | `GatewaySettings.from_env` only binds an upstream whose env pair is set. Without the Anthropic pair the gateway has no Anthropic upstream and **every mint is refused** — gateway selection is fail-closed (`GatewayMintError`), so this is a stopped factory, not a degraded route. `gateway_binding_gaps()` names the missing variables at boot rather than leaving N spawn failures to interpret. |


1. **Bind Anthropic on the gateway** and restart it.
   *Verify:* the accounts view reports the Anthropic account `configured`
   rather than `UNVERIFIED / CREDENTIAL_MISSING`.
2. **Run.** The dials already default to `gateway`; nothing else is needed.
   *Verify:* new ledger rows carry `upstream_provider: anthropic` with a
   `principal` naming the role, spawn, session and issue.
3. **Later, if the last roles matter:** move execution to docker and arm the
   fleet ratchet. Only then does `gateway_fleet_ratchet_enabled` become a
   candidate for defaulting `True`, because a host-mode config would no longer
   be a supported shape.

Each step is independently reversible, and each has an observable that is not
"it seems to work": the ledger either contains the rows or it does not.

## Consequences

**Good.** One question — "what did this role spend on this issue" — gets one
answer, for every provider, from one file. Cost dials that read an empty surface
(`daily_cost_budget_usd`, `cost_throttle_ratio`, `issue_cost_alert_usd`) start
measuring something. Credential blast radius shrinks to a per-spawn minted key
with a lease.

**Costs.** The gateway becomes a hard dependency for every dialled role: if it
is down, those spawns fail closed rather than quietly falling back to a direct
CLI. That is the point — a silent fallback is exactly how the ledger came to
record one provider for two days — but it means gateway availability is now
factory availability.

**Risk accepted.** A single process now sees every prompt and every response.
`GATEWAY_BODY_CAPTURE_REPOS` gates body capture per repo, and ADR-0085's
scrubbing applies, but the concentration is real and deliberate.

**What this does not do.** It does not consolidate the historical
`inferences.jsonl` ledgers. Each is a hash-linked audit stream
(`AuditStreamSpec(name="inference_telemetry")`); concatenating them would break
the chain that makes them evidence. They stay readable where they are, and the
gateway ledger becomes the record from the migration forward.
