# ADR-0109: Provider/Harness Backend Split — z.ai as a Claude-harness backend

**Status:** Accepted
**Accepted on:** 2026-07-25 — operator-approved (route agentic maintenance loops to GLM while work stays on Claude).
**Date:** 2026-07-25
**Enforcement:** enforced
**Enforced by:** pytest:tests/test_config_combo_env.py::test_reject_glm_model_on_claude_provider
**Amends:** ADR-0001 (Five Concurrent Async Loops — background workers gain a per-role harness backend dial)

## Context

HydraFlow spawned every worker through two entangled axes: `*_tool`
(`Literal["claude","codex","gemini","pi"]` — which agentic CLI binary) and
`*_provider` (`Literal["claude","openrouter","zai","kimi"]` — which
OpenAI-compatible HTTP backend, present only on the 7 one-shot no-tools loops).
An inline comment in `src/runner_utils.py` asserted the load-bearing
assumption: *"the agentic path stays on the Claude harness — Anthropic doesn't
support routing it to non-Claude models."*

That assumption is only half true. z.ai / GLM ships an **Anthropic-compatible**
endpoint (`/api/anthropic`) built for exactly this: point the Claude CLI at it
via `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` and the agentic, tool-using
harness runs on GLM. So an operator can run *maintenance on GLM, work on
Claude* — the one-shot maintenance loops already route to z.ai over HTTP; the
agentic ones could not.

Two other problems compounded it:

- **`background_model` was a blunt global.** When set it back-filled every
  default `*_model` (`_apply_profile_overrides`), which silently stranded a GLM
  model on a claude-provider (Anthropic) role — a config Anthropic rejects.
- **Credit exhaustion on the agentic path was a universal kill switch.**
  `raise_if_credit_exhausted` raised with no provider (→ `anthropic`), so a GLM
  cap on a z.ai-routed spawn would pause *Claude* work. The one-shot HTTP path
  already scoped per-provider (ADR-lineage #9807); the agentic path did not.

## Decision

**1. Two orthogonal axes.** `tool` = which CLI binary (`claude` | `codex` —
gemini and pi are removed; only two harnesses are supported). `provider` =
which API/billing backend (`claude` | `zai`), now available on **every** role,
not just the one-shot loops.

**2. z.ai has two registry faces.** The existing one-shot HTTP face
(`zai_base_url` → `/api/paas/v4`) is joined by a **harness** face
(`zai_harness_base_url` → `/api/anthropic`, `src/runner_utils.py:_HARNESS_BACKENDS`),
consumed by the Claude CLI. Both authenticate from `ZAI_API_KEY` (env-only
secret).

**3. Per-spawn env, never global.** `src/runner_utils.py:resolve_harness_env`
returns `{}` for `claude`/`anthropic` (a pristine env — the main workers are
untouched) and, for `zai`, `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` while
clearing `ANTHROPIC_API_KEY` so a host key can't shadow the token. It is merged
into a per-spawn env in `stream_claude_process` and `_claude_cli_complete` —
**never exported globally**, which is the invariant that keeps every
`provider=claude` spawn on Anthropic regardless of z.ai config elsewhere.

**4. Provider-scoped model validation.** `_harmonize_tool_model_defaults`
validates the `(tool, provider, model)` triple: a `glm-*` model requires
`provider=zai` and `tool=claude`; a `zai` provider requires a `glm-*` model.
This turns the old silent leak into a loud config-load error. A coherent
`maintenance_provider`/`maintenance_model` knob routes the maintenance role-set
together (provider AND model), never the work loops.

**5. Per-(tool, api) credit scoping.** Both credit checks
(`raise_if_credit_exhausted`, `_post_stream_result`) tag `CreditExhaustedError`
with the resolved provider, so a GLM cap pauses only z.ai-routed loops and an
Anthropic cap only Anthropic-routed loops. The z.ai/GLM billing phrasings are
added to `src/subprocess_util.py:_CREDIT_PATTERNS` for the harness (stderr) path.

**6. Runner activation.** `src/base_runner.py:BaseRunner` resolves each runner's
provider via an overridable `_resolve_provider()` / `PROVIDER_FIELD` hook; the
four core streaming runners (implementation/planner/review/triage) set their
dial. Default `claude` is a no-op, so behavior is unchanged until an operator
flips a dial.

## Consequences

- An operator routes any wired role to GLM by config alone (no code change):
  set the role's `*_provider=zai` and a `glm-*` model, or use `maintenance_*`.
- The main coding workers stay on Claude by default; the isolation invariant
  (per-spawn override) guarantees a z.ai config can't hijack them.
- A backend cap is scoped, not global — GLM exhaustion no longer halts Claude
  work.
- The tool axis is `claude`+`codex` only; gemini/pi are un-configurable and
  un-spawnable (their inert transcript-shape parsers remain as defensive code).

## Alternatives considered

- **A new `claude-zai` tool enum value** — re-fuses CLI and endpoint into one
  axis (the coupling this ADR removes) and pushes credit scoping into
  tool-string parsing. Rejected.
- **A full backend-profile registry** (every role → a named backend record) —
  cleanest long-term but the largest refactor; deferred until a third harness
  backend appears. This split can grow into it.

## Related

- Follow-ups (not in the landing PR): route a top-level agentic *work* loop to
  z.ai with orchestrator pause-scoping (extend
  `orchestrator.py:_BACKEND_WORKER_LOOPS`); telemetry cost attribution for
  agentic-on-z.ai spend; a MockWorld scenario + sandbox e2e for the harness
  routing; a `sentry_provider` dial. The one-shot maintenance loops already
  route to z.ai over HTTP today.
- Spec: `docs/superpowers/specs/2026-07-25-provider-backend-split-zai-harness.md`.
