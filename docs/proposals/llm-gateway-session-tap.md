# LLM gateway: the session tap

**Status:** implemented behind opt-in gateway configuration (2026-08-19); deterministic conformance, MockWorld, sandbox, and same-request live-provider capture evidence are present. **Amends:** ADR-0110 (provider/harness backend split — the gateway becomes a first-class harness backend, and eventually the only one workers see). **Kin:** ADR-0093 (loop fitness as measured contract — gateway coverage is a gauge, not a promise), the pricing-refresh loop (ADR-0078 — the cost oracle the ledger prices against).

## The gap

Every LLM-consuming surface in the factory authenticates and reports for itself. Provider keys ride host env vars into per-spawn container envs (`ANTHROPIC_API_KEY`, `ZAI_API_KEY`); usage visibility depends on each tool's own stream — transcripts here, credit-probe heuristics there, nothing anywhere for a loop someone forgot to instrument. That is the measurement-blindness pattern in its purest form: the denominator of "what did the org spend, on what, from where" is a hand-maintained list of emitters, and hand-maintained lists are this factory's recurring defect.

The fix is structural, not diligence: put one chokepoint in the path and make it impossible to spend org tokens without being observed. **Nothing authenticates except through the gateway; therefore the ledger is complete by construction.** Config surface per tool collapses to two values it needed anyway — a base URL and a key.

In control terms the gateway is a sensor in v1 and an actuator in v2, in that order. Model routing, per-principal budgets, org-wide credit pause — all become config at the chokepoint once traffic transits it. None of it ships before the sensor has burned in: you calibrate the gauge before you wire it to the actuator.

## Design

### Shape (decided)

One new deployable, `hydraflow-gateway`: FastAPI + httpx, two planes in one codebase.

- **Data plane** — a deliberately boring Anthropic-compatible reverse proxy. Wildcard passthrough of everything under the base path (the CLI hits more than `/v1/messages`; an endpoint whitelist is a hand-maintained list). SSE streams forwarded chunk-for-chunk; upstream errors, 429s, and `overloaded` responses passed through verbatim so client retry behavior is indistinguishable from direct. All request headers forward verbatim — explicitly including `anthropic-beta`, which carries the OAuth capability subscription sessions require upstream; this single rule is what makes the gateway subscription-compatible ([llm-gateway-protocol](https://code.claude.com/docs/en/llm-gateway-protocol.md)). The less clever the pipe, the more transparent the tap.
- **Control plane** — key minting and the ledger. Real provider keys exist only in the gateway's env. Nothing credentialed reaches an agent container again.

**Fail-closed.** A bypass key would break the completeness invariant, so there is none. Gateway availability is fleet availability; acceptable for the factory on its own deploy, and the explicit gate on org-wide onboarding (see out-of-scope).

### Identity is the key (decided)

The control plane mints short-lived virtual keys carrying the org-shaped principal model from day one, even though v1 clients are only factory spawns:

- **principal** — loop / role / spawn now; person / team later. The shape is org-ready so onboarding humans and other tools is new rows, not an auth rework.
- **repo class** — `hydraflow` | `client` | `personal`.
- **provider binding** — which upstream this key may reach (`anthropic` | `zai-harness`), reusing ADR-0110's backend registry server-side.
- **body-capture policy** — stamped at mint (see ledger). Governance is decided per principal at mint time, never globally.
- **TTL** — keys die with their spawn.

A key per spawn means **the key is the session handle**. Session reconstruction is mechanical — no header archaeology, no per-tool correlation stream. This is the tap.

### Wiring (decided)

`resolve_harness_env()` gains a `gateway` entry in `_HARNESS_BACKENDS`: mint (or fetch) the spawn's key → `ANTHROPIC_BASE_URL` = gateway → `ANTHROPIC_AUTH_TOKEN` = virtual key → `ANTHROPIC_API_KEY` cleared. ADR-0110's invariants survive untouched: per-spawn env, never global; provider-scoped model validation; per-provider credit scoping (the gateway forwards upstream billing errors verbatim, so existing `CreditExhaustedError` tagging keeps working unmodified).

Rollout rides the existing per-role provider dials: one maintenance loop first, then ratchet role by role until `gateway` is the default and direct provider values are config errors. The ratchet's final state — no worker holds a real key — is the security payoff, and it lands via config, not code.

### Ledger (decided)

`GatewayLedger(AppendOnlyJsonlLedger)`, one row per request: principal, key id, session/spawn id, model requested, model served, tokens in/out/cache-read/cache-write, latency, status, upstream provider, and cost priced by the pricing-refresh loop's tables. Metadata is always captured.

**Bodies only by policy.** Full prompt/response capture happens iff the minted policy says so — expected: factory repos yes, client and personal repo classes no — stored separately from the metadata ledger with its own retention. The factory does not build a data lake of client source as a side effect of observability.

### Coverage as a measured contract (decided)

The one-shot OpenAI-compatible loops (`openrouter` | `kimi` HTTP faces) bypass v1. That gap is **observed, not forgotten**: a read-only caretaker computes % of org LLM spend transiting the gateway — gateway ledger over gateway ledger plus the bypass traffic, which in v1 is exclusively in-framework one-shot loops whose HTTP clients already self-report usage in-process (self-report is the exact weakness the gateway retires, which is why the gauge exists) — and renders it as a dashboard gauge per ADR-0093. The gauge's job is to make "the tap is partial" impossible to not-know, and to give the OpenAI-face fast-follow its finish line: coverage → 100%, at which point the gauge becomes a regression tripwire.

### V2 at the chokepoint — routing and cost control (direction, not v1)

Once traffic transits: per-principal budgets, model allowlists, model aliasing (`sonnet` → org policy's current answer), org-wide credit-pause relocated server-side, provider routing on ADR-0110's axes. Two guardrails ruled now so v2 inherits them:

1. **The gateway enforces and aliases; it never silently rewrites a model mid-session.** An agent that asked for one model and unknowingly got another is a harness lying to itself. Every routing decision lands in the ledger — `model requested` vs `model served` is a first-class pair.
2. **No enforcement before the sensor is calibrated.** Budgets act on ledger-derived spend; the ledger earns trust first.

### Testing (decided)

The engineering risk is streaming transparency, so it gets the fixture treatment:

- **SSE conformance suite** — long streams, tool_use turns, interleaved thinking, mid-stream client aborts, 429/overloaded retry passthrough — diffing gateway-transited responses against direct fixtures. Golden pass-through: byte-identical modulo hop headers.
- **Mockworld scenario** — mint → spawn → transit → ledger row → coverage gauge, end to end against the fake-LLM sandbox (`docker-compose.sandbox.yml` already stubs `ANTHROPIC_API_KEY`; the gateway slots in front of the same fake).
- Coverage on passthrough and ledger is contractual, per the standard the factory quotes to other people's clients.

### Sequencing (decided)

1. **Hour one: the confidence probe.** ~50-line FastAPI/httpx streaming passthrough, one real agentic session through it, diff against direct. ADR-0110's z.ai face is the existence proof that the CLI transits Anthropic-compatible endpoints; this probe proves *our* pipe specifically. Half a day converts the streaming risk to near-zero before any real build.
2. Data plane + conformance suite.
3. Control plane: mint API, key store, TTL reaping.
4. Wiring: `_HARNESS_BACKENDS` entry, per-role dial, first maintenance loop live.
5. Ledger + pricing join + dashboard gauge.
6. Ratchet roles until direct is a config error.

## Implementation status (2026-08-19)

The deployable data/control planes, virtual-key harness wiring, append-only
ledger, read-only coverage loop and dashboard gauge are implemented. The test
pyramid includes deterministic pass-through fixtures, an in-process MockWorld
scenario, and the `s91_gateway_session_tap.py` Docker sandbox scenario.

The committed live-provider artifact records two z.ai-bound agentic turns and
compares each downstream stream with the gateway's upstream body capture for
that exact request. Both byte counts and SHA-256 values match, and the raw
request/response captures were deleted before the sanitized artifact was
written. The embedded queued-agent receipt keeps issue-specific planner
outcomes separate from shared gateway observation-window totals so concurrent
keys are not misattributed. This closes the live streaming-transparency evidence
gap; rollout remains opt-in until the operational burn-in and ratchet are
separately approved.

## Out of scope, explicitly

- **Enforcement of any kind** (budgets, allowlists, pause) — v2, after burn-in.
- **OpenAI-compatible face** for the one-shot loops — fast-follow, finish line defined by the coverage gauge.
- **OAuth/subscription session onboarding** — the transit question is answered by documentation, not a spike: setting `ANTHROPIC_BASE_URL` *without* a gateway credential is the documented pattern for routing a subscription session through a gateway — the claude.ai login stays the active credential (its billing and limits apply), the gateway forwards the opaque bearer plus the `anthropic-beta` OAuth capability, and token acquisition/refresh flows bypass the gateway entirely (direct to `oauth.claude.ai` — a feature: the gateway never touches credential lifecycle). What remains for org onboarding is a design item, not a feasibility one: **principal attribution for sub sessions needs a side channel** (the bearer is opaque and no key is minted — candidates: per-user hostname/path or a companion header), and their ledger rows carry real tokens but notional cost (plan quota, not per-token dollars). Note: standalone Claude Code has no OTel export — telemetry export exists only via Anthropic's own Claude apps gateway product, so wire transit through this gateway (or adopting Anthropic's gateway for the human slice) are the two live options for observing sub sessions; there is no third telemetry-only path.
- **HA** — fail-closed on the factory's deploy is accepted; an availability story gates onboarding anyone whose work stops when the gateway does.
- **Multi-region / data-residency routing** — the principal model leaves room (repo class); nothing more now.

## The one-line version

Nothing spends without being seen: one boring pipe, identity in the key, the ledger complete by construction — sensor first, actuator second.
