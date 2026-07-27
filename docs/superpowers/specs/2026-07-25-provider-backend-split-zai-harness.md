# Provider/Harness Backend Split — z.ai as a Claude-harness backend

**Status:** Draft (brainstormed 2026-07-25)
**Owner:** factory (autonomous)
**Supersedes assumption:** the inline claim at `runner_utils.py` that "the agentic path stays on the Claude harness — Anthropic doesn't support routing it to non-Claude models." An ADR will formalize the supersession.

## 1. Problem

HydraFlow routes every worker through two entangled axes that were never cleanly separated:

- **`*_tool`** (`Literal["claude","codex","gemini","pi"]`) — which agentic CLI binary spawns. Every role has one.
- **`*_provider`** (`Literal["claude","openrouter","zai","kimi"]`) — which API/billing backend a **one-shot, no-tools** loop calls over HTTP. Only the 7 one-shot roles have one.

Two consequences the operator hit in practice:

1. **The agentic maintenance loops cannot run on z.ai.** They need tools, so they run the Claude CLI harness, which today is hard-wired to Anthropic. z.ai is only reachable on the one-shot HTTP path. The operator wants *maintenance on GLM, work on Claude* — impossible for the agentic maintenance loops (wiki compiler, ADR reviewer, sentry, drift-resolver).
2. **`background_model` is a blunt global.** When set, it back-fills every default `*_model` (`config.py` `_apply_if_default`), which is how `glm-5.2` silently leaked onto `transcript_summary_model` and `adr_review_model`. Nothing stops it landing `glm-5.2` on a role whose provider is still `claude@anthropic` — a config Anthropic would reject at call time.
3. **Credit exhaustion on the agentic path is a universal kill switch.** `raise_if_credit_exhausted()` raises `CreditExhaustedError` with no `provider`, defaulting to `anthropic`. The moment a claude-harness worker points at z.ai, a GLM 429 is mis-attributed to Anthropic and pauses *Claude* work. The one-shot HTTP path already scopes per-provider (`#9807`); the agentic path does not.

## 2. Goals / Non-goals

**Goals**
- Add **z.ai as a first-class Claude-harness backend**: `tool=claude` runs the Claude CLI against z.ai's Anthropic-compatible endpoint (`/api/anthropic`), selected per-role via `provider`.
- Cleanly separate the two axes: `tool` = which CLI; `provider` = which API/billing backend. `provider` becomes available on **every** role.
- Make model routing **provider-aware and explicit** — no blunt global back-fill into work loops.
- Scope credit exhaustion **per (tool, api)** so a GLM cap pauses only z.ai-routed loops, and an Anthropic cap only Anthropic-routed loops.
- **Prune the tool axis to `claude` + `codex`.** Remove `gemini` and `pi` entirely (only two harnesses supported going forward).

**Non-goals**
- `kimi` as a harness backend — stays one-shot HTTP only. YAGNI until agentic Kimi is actually wanted.
- A full generic backend-profile registry (the "Approach 3" option). Approach 1 can grow into it later if a third harness backend appears.
- Changing which *models* the operator runs — this is about *routing*, not model selection policy.

## 3. Resolution model

Every role resolves a triple **`(tool, provider, model)`**:

| axis | values after this change | meaning |
|---|---|---|
| `tool` | `claude` \| `codex` | which CLI binary (gemini/pi removed) |
| `provider` | `claude` \| `zai` (+ `openrouter`/`kimi` on one-shot roles only) | which API/billing backend |
| `model` | e.g. `sonnet`, `glm-5.2` | model id, validated against `provider` |

`normalize_provider("claude") == "anthropic"` (unchanged) — the dial spells the harness `claude`; billing/credit identity spells it `anthropic`.

**z.ai gets two faces in the backend registry:**

- One-shot HTTP (exists): `zai_base_url = https://api.z.ai/api/paas/v4` → `POST /chat/completions`.
- **Harness-compat (new): `zai_harness_base_url = https://api.z.ai/api/anthropic`** → consumed by the Claude CLI via `ANTHROPIC_BASE_URL`.
- Both authenticate from `ZAI_API_KEY` (env-only secret; never persisted to config, never shown in UI).

**Resolution table:**

| role kind | `provider=claude` | `provider=zai` |
|---|---|---|
| **agentic** (implement, review, plan, triage, wiki, adr-review, sentry, drift-resolver, …) | Claude CLI @ Anthropic *(today)* | Claude CLI @ z.ai `/api/anthropic`, **per-spawn env**, `model=glm-*` |
| **one-shot** (honeypot, pr-unstick, term-proposer, transcript, …) | Claude CLI lightweight *(today)* | direct `POST /paas/v4` *(today)* |

Only the top-right cell is a new code path.

## 4. Design

### 4.1 Prune gemini / pi (do this first — smaller surface for everything after)

- `AgentTool` (`agent_cli.py`) → `Literal["claude","codex"]`. Remove the gemini/pi command-builder branches.
- Every `*_tool` Literal in `config.py` → `Literal["claude","codex"]` (and `Literal["inherit","claude","codex"]` for `system_tool`/`background_tool`).
- Drop the `("gemini","gemini")` row from `_MODEL_TOOL_REQUIRED`; keep the codex rows (`gpt-`/`o1`/`o3`/`o4`).
- Sweep `models.py`, `judge_independence.py`, `admin_tasks.py`, `stream_parser.py`, `activity_parser.py`, `trace_collector.py`, `runner_utils.py` for gemini/pi handling and remove.
- **Targeted removal only** — `"pi"` is a common substring; remove it strictly where it is an `AgentTool` value/branch, never by blanket text match. Verified against **full `make quality`**, not a test subset (backend removal has higher blast radius than its diff; cf. the repo's PR #8460 over-prune lesson).

### 4.2 z.ai harness backend

- Backend registry entry for z.ai gains a `harness_base_url` alongside the existing one-shot `base_url`; both resolve `ZAI_API_KEY`.
- New `zai_harness_base_url` config field (UI-editable, non-secret), default `https://api.z.ai/api/anthropic`.

### 4.3 Config surface

- **Un-force `background_model` / `background_tool`.** Remove them from the blanket `_apply_if_default` back-fill (`config.py`). Each role carries its own `(provider, model)`. Replace the global with a **`maintenance_provider` / `maintenance_model`** default that applies **only** to the maintenance role-set (wiki, adr-review, transcript-summary, sentry, drift-resolver, term-proposer, triage-honeypot, pr-unstick) and **never** to implement/review/plan/triage/AC. Explicit and visible in config — not a hidden back-fill.
- **Extend `*_provider` to every agentic role**: `implementation_provider`, `review_provider`, `planner_provider`, `triage_provider`, `ac_provider`, `subskill_provider`, `debug_provider`, `verification_judge_provider`, `test_adequacy_verifier_provider`, plus `system`/`background`. All default `claude`. On agentic roles the Literal is `["claude","zai"]` (harness backends only); one-shot roles keep `["claude","openrouter","zai","kimi"]`.
- **Provider-scoped model validation** in `_harmonize_tool_model_defaults`: validate the `(tool, provider, model)` triple. `glm-*` ⇒ `provider=zai` **and** `tool=claude` (rides the Claude harness). `opus`/`sonnet`/`haiku`/`claude-*` ⇒ `provider=claude`. Reject `glm@anthropic` and `opus@zai` at config-load time.

### 4.4 Spawn seam (the only new code path)

`resolve_harness_env(provider, config) -> dict[str,str]`:
- `provider in {claude, anthropic}` → `{}` (main workers get a pristine Anthropic env — untouched, guaranteed).
- `provider == zai` → `{"ANTHROPIC_BASE_URL": config.zai_harness_base_url, "ANTHROPIC_AUTH_TOKEN": <ZAI_API_KEY>}`, and **clear** any inherited `ANTHROPIC_API_KEY` so a host Claude key can't shadow the z.ai token.

Injected **per-spawn**, never global:
```
env = make_clean_env(gh_token)
env.update(resolve_harness_env(provider, config))
```
at both CLI spawn points — `_claude_cli_complete` (lightweight) and `stream_claude_with_telemetry` (streaming heavy path). Both gain a `provider` parameter that callers thread from the role's resolved dial. `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` added to the `make_clean_env` allowlist so they survive the strip.

**Isolation invariant:** a `provider=claude` spawn receives no base-url override. This is the safety property that keeps the main coding workers on Anthropic regardless of any z.ai config elsewhere.

### 4.5 Credit scoping (kills the universal kill switch)

- `raise_if_credit_exhausted(stdout, stderr, tool, provider="claude")` → `CreditExhaustedError(..., provider=normalize_provider(provider))`. Default keeps every existing call site behavior-identical (Anthropic-scoped).
- Same `provider` tag on the streaming path's credit check (`_post_stream_result`).
- Extend the orchestrator's loop→provider map to cover the agentic loops that now carry a provider dial. The existing per-provider pause machinery (`_credit_paused_provider`) then already scopes: a GLM 429 pauses only z.ai-routed loops; Claude work continues, and vice-versa.
- **Detection fidelity:** on the harness-on-z.ai path, a GLM cap surfaces through the *Claude CLI's* stderr, not a raw HTTP 429, and won't carry Claude's "usage limit reached" phrasing. Add z.ai/anthropic-compat quota/credit error strings to `is_credit_exhaustion()`, pinned by a **contract cassette** of the real GLM stderr shape. This is the one place detection could silently regress → dedicated test.

### 4.6 Docker, telemetry

- **Docker:** the override rides the per-spawn env dict, so it propagates into the containerized workspace subprocess naturally. Must-checks: `ZAI_API_KEY` is passed into the factory container env; the sandbox air-gap does not strip `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN`.
- **Telemetry/cost:** attribute agentic-on-z.ai spend to `zai`, not `anthropic` (mirror the one-shot `_telemetry_cmd` head=provider), so the cost dashboard separates GLM spend from Claude.

## 5. Testing (full pyramid — load-bearing feature)

- **Unit:** `resolve_harness_env` returns `{}` for claude / correct env for zai and clears `ANTHROPIC_API_KEY`; credit tag carries provider on both paths; `(tool,provider,model)` validation rejects `glm@anthropic` and `opus@zai`; un-force no longer leaks `background_model`/`maintenance_*` into work roles; gemini/pi fully removed from `AgentTool` and no dangling branches.
- **MockWorld scenario:** a maintenance loop routed to `zai` hits a simulated 429 → only zai-routed loops pause; implement/review keep running (the anti-universal-kill-switch assertion).
- **Sandbox e2e:** docker spawn of an agentic maintenance loop with `provider=zai` actually receives `ANTHROPIC_BASE_URL` pointing at a fake z.ai endpoint and completes end-to-end; assert the main claude worker spawns get **no** base-url override (isolation).
- **Contract cassette:** pin the real GLM `/api/anthropic` 429 / quota stderr shape feeding `is_credit_exhaustion`.

## 6. ADR

New ADR superseding the "agentic path stays on Claude" assumption (`runner_utils.py`), recording: the two-faced z.ai registry, per-spawn env isolation, per-provider credit scoping, and the `claude`+`codex`-only tool axis.

## 7. Rollout / follow-ups

- Ship as one PR to `staging`: (1) prune gemini/pi → (2) z.ai harness backend + config surface → (3) credit scoping → (4) tests + ADR. Cleanly separated commits for reviewability.
- After merge, the operator flips maintenance roles to `provider=zai` via config (no code change) — the existing `.hydraflow/config.json` dials.
- Follow-up (not this PR): generalize to the backend-profile registry only if a third harness backend appears.

## 8. Non-obvious constraints captured

- Env override is **per-spawn, derived from the role's dial** — never a global env var. A global `ANTHROPIC_BASE_URL` would silently hijack the main Claude workers.
- `ZAI_API_KEY` is a secret — env-only, never on `HydraFlowConfig`, never in the settings UI.
- Backend removal (gemini/pi) is verified with **full `make quality`**, never a targeted test subset.
