# Provider/Harness Backend Split — z.ai as Claude-harness backend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route agentic maintenance loops to z.ai (GLM) via the Claude CLI's Anthropic-compatible endpoint while keeping implement/review/plan/triage on Claude, with per-provider credit scoping and a pruned `claude`+`codex` tool axis.

**Architecture:** Separate two axes — `tool` (which CLI: `claude`|`codex`) and `provider` (which API/billing backend: `claude`|`zai`). z.ai gains a second registry face (`/api/anthropic`) consumed by the Claude CLI via a per-spawn `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` override that is never global. Credit exhaustion is tagged with the resolved provider so a GLM cap pauses only z.ai-routed loops.

**Tech Stack:** Python 3.12, Pydantic v2 (`HydraFlowConfig`), pytest + hypothesis, httpx, the Claude/codex CLI harnesses, docker sandbox scenarios.

## Global Constraints

- Never commit to `main`; this branch (`feat/provider-split-zai-harness`) PRs to `staging`.
- Never `git commit --no-verify` / `--no-hooks`. Fix code first.
- `ZAI_API_KEY` is a secret: env-only, never on `HydraFlowConfig`, never in the settings UI, never logged.
- The endpoint override is **per-spawn, derived from the role's dial** — never a global `ANTHROPIC_BASE_URL`.
- `provider=claude` spawns MUST receive no base-url override (isolation invariant).
- `normalize_provider("claude") == "anthropic"`; the dial spells `claude`, billing spells `anthropic`.
- Backend removal (gemini/pi) verified with **full `make quality`**, never a targeted subset.
- Load-bearing feature → full test pyramid: unit + MockWorld scenario + sandbox e2e.
- Every `fix(` commit needs a `tests/regressions/` delta or a `Skip-Regression:` trailer (P10.6). Prefer real regression tests.

---

## Phase A — Prune gemini / pi (smaller surface for everything after)

### Task 1: Remove gemini/pi from the AgentTool harness

**Files:**
- Modify: `src/agent_cli.py` (`AgentTool` literal + command-builder branches)
- Modify: `src/config.py` (`_MODEL_TOOL_REQUIRED` — drop the gemini row)
- Test: `tests/test_agent_cli.py`

**Interfaces:**
- Produces: `AgentTool = Literal["claude","codex"]`; `build_lightweight_command(tool, ...)` raises on any non-{claude,codex} tool.

- [ ] **Step 1: Write failing test** — assert the enum shrank and unknown tools are rejected.

```python
def test_agent_tool_is_claude_and_codex_only():
    import agent_cli
    assert set(agent_cli.AgentTool.__args__) == {"claude", "codex"}

def test_build_lightweight_command_rejects_removed_tools():
    from agent_cli import build_lightweight_command
    for dead in ("gemini", "pi"):
        with pytest.raises((ValueError, KeyError, AssertionError)):
            build_lightweight_command(tool=dead, model="x", prompt="p")
```

- [ ] **Step 2: Run — expect FAIL** (`pytest tests/test_agent_cli.py -k "claude_and_codex or rejects_removed" -v`).
- [ ] **Step 3: Implement** — set `AgentTool = Literal["claude","codex"]`; delete the `if tool == "gemini":` and `if tool == "pi":` branches in `build_lightweight_command` and the streaming builder; make the fallthrough raise `ValueError(f"unsupported tool {tool!r}")`. Remove the `("gemini","gemini")` row from `_MODEL_TOOL_REQUIRED` in `config.py` (keep the codex `gpt-`/`o1`/`o3`/`o4` rows).
- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `refactor(harness): drop gemini/pi — support claude+codex only`.

### Task 2: Sweep residual gemini/pi references across src + config Literals

**Files:**
- Modify: every `*_tool` Literal in `src/config.py` → `Literal["claude","codex"]` (and `["inherit","claude","codex"]` for `system_tool`/`background_tool`)
- Modify (sweep): `src/models.py`, `src/judge_independence.py`, `src/admin_tasks.py`, `src/stream_parser.py`, `src/activity_parser.py`, `src/trace_collector.py`, `src/runner_utils.py`
- Test: `tests/test_config.py`, plus grep guard

**Interfaces:**
- Consumes: Task 1's `AgentTool`.
- Produces: no `"gemini"`/`"pi"` `AgentTool` value anywhere in `src/`.

- [ ] **Step 1: Write failing guard test** — no gemini/pi tool literal survives in config.

```python
def test_no_gemini_or_pi_tool_literal_in_config():
    import config, inspect
    src = inspect.getsource(config)
    # tool-axis literals only; substring 'pi' is fine elsewhere
    assert '"gemini"' not in src
    for name, field in config.HydraFlowConfig.model_fields.items():
        if name.endswith("_tool"):
            args = getattr(field.annotation, "__args__", ())
            assert "gemini" not in args and "pi" not in args, name
```

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** — narrow all `*_tool` Literals; grep each sweep file (`grep -nE '"gemini"|== "pi"|"pi"'`) and remove only genuine `AgentTool`-valued branches/lists (leave unrelated `pi`/`Pi` substrings). Fix any resulting exhaustiveness branches.
- [ ] **Step 4: Run — expect PASS**; then `grep -rInE '"gemini"' src/ | grep -v test` returns nothing tool-related.
- [ ] **Step 5: Commit** — `refactor(harness): sweep residual gemini/pi tool references`.

---

## Phase B — z.ai harness registry + config surface

### Task 3: Add the z.ai harness registry face + config field

**Files:**
- Modify: `src/runner_utils.py` (`_OpenAICompatBackend` registry / add harness base-url resolution)
- Modify: `src/config.py` (add `zai_harness_base_url` field)
- Test: `tests/test_llm_provider.py`

**Interfaces:**
- Produces: `config.zai_harness_base_url` (default `https://api.z.ai/api/anthropic`); `runner_utils.harness_base_url(provider, config) -> str` (`""` when provider is not a harness backend).

- [ ] **Step 1: Write failing test.**

```python
def test_zai_harness_base_url_default_and_lookup():
    from config import HydraFlowConfig
    from runner_utils import harness_base_url
    cfg = HydraFlowConfig()
    assert cfg.zai_harness_base_url == "https://api.z.ai/api/anthropic"
    assert harness_base_url("zai", cfg) == cfg.zai_harness_base_url
    assert harness_base_url("claude", cfg) == ""
    assert harness_base_url("anthropic", cfg) == ""
```

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** — add the field (UI-editable, non-secret); add `harness_base_url()` returning the config field for `zai`, `""` otherwise.
- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `feat(provider): add z.ai harness (/api/anthropic) registry face`.

### Task 4: Extend `*_provider` dials to every agentic role

**Files:**
- Modify: `src/config.py` (add provider fields for the agentic roles; agentic Literal = `["claude","zai"]`)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `implementation_provider`, `review_provider`, `planner_provider`, `triage_provider`, `ac_provider`, `subskill_provider`, `debug_provider`, `verification_judge_provider`, `test_adequacy_verifier_provider`, `system_provider`, `background_provider` — all `Literal["claude","zai"]`, default `"claude"`.

- [ ] **Step 1: Write failing test.**

```python
def test_agentic_roles_have_provider_dial_defaulting_claude():
    from config import HydraFlowConfig
    cfg = HydraFlowConfig()
    for role in ("implementation","review","planner","triage","ac",
                 "subskill","debug","verification_judge",
                 "test_adequacy_verifier","system","background"):
        assert getattr(cfg, f"{role}_provider") == "claude"
```

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** — add the fields with `Literal["claude","zai"]` default `"claude"`.
- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `feat(config): provider dial on every agentic role`.

### Task 5: Un-force background_model + provider-scoped model validation

**Files:**
- Modify: `src/config.py` (remove `background_model`/`background_tool` from `_apply_if_default`; add `maintenance_provider`/`maintenance_model` scoped to the maintenance role-set; extend `_harmonize_tool_model_defaults`)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `maintenance_provider` (`Literal["claude","zai"]`, default `"claude"`), `maintenance_model` (`str`, default `""`); validation rejecting `glm@anthropic` and `opus@zai`.

- [ ] **Step 1: Write failing tests.**

```python
def test_background_model_no_longer_leaks_into_work_roles():
    from config import HydraFlowConfig
    cfg = HydraFlowConfig(background_model="glm-5.2")  # legacy knob
    # work roles keep their own model, never back-filled
    assert cfg.model != "glm-5.2"          # implementation
    assert cfg.review_model != "glm-5.2"

def test_maintenance_default_only_touches_maintenance_roles():
    from config import HydraFlowConfig
    cfg = HydraFlowConfig(maintenance_provider="zai", maintenance_model="glm-5.2")
    assert cfg.wiki_compilation_provider == "zai"
    assert cfg.implementation_provider == "claude"   # never work roles

def test_reject_glm_on_anthropic_and_opus_on_zai():
    from config import HydraFlowConfig
    with pytest.raises(Exception):
        HydraFlowConfig(implementation_provider="claude", model="glm-5.2")
    with pytest.raises(Exception):
        HydraFlowConfig(wiki_compilation_provider="zai", wiki_compilation_model="opus")
```

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** — delete the `background_model`/`background_tool` blocks from `_apply_if_default`; add `maintenance_*` applied only to the maintenance role-set (wiki, adr-review, transcript-summary, sentry, adr-drift-resolver, term-proposer, triage-honeypot, pr-unstick); in `_harmonize_tool_model_defaults` validate the `(tool,provider,model)` triple (`glm-*` ⇒ provider zai & tool claude; `opus`/`sonnet`/`haiku`/`claude-*` ⇒ provider claude).
- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `feat(config): maintenance default + provider-scoped model validation`.

---

## Phase C — Spawn seam + isolation

### Task 6: `resolve_harness_env` resolver

**Files:**
- Modify: `src/runner_utils.py` (add `resolve_harness_env`)
- Test: `tests/test_llm_provider.py`

**Interfaces:**
- Produces: `resolve_harness_env(provider: str, config: HydraFlowConfig) -> dict[str,str]`.

- [ ] **Step 1: Write failing test.**

```python
def test_resolve_harness_env_isolation_and_zai(monkeypatch):
    from config import HydraFlowConfig
    from runner_utils import resolve_harness_env
    cfg = HydraFlowConfig()
    # claude/anthropic -> pristine (no override)
    assert resolve_harness_env("claude", cfg) == {}
    assert resolve_harness_env("anthropic", cfg) == {}
    # zai -> base url + token, and clears ANTHROPIC_API_KEY
    monkeypatch.setenv("ZAI_API_KEY", "sk-zai-test")
    env = resolve_harness_env("zai", cfg)
    assert env["ANTHROPIC_BASE_URL"] == cfg.zai_harness_base_url
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-zai-test"
    assert env.get("ANTHROPIC_API_KEY") == ""   # shadow-guard
```

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** — `{}` for claude/anthropic; for zai read `ZAI_API_KEY` via the registry, return the three keys (empty `ANTHROPIC_API_KEY` to clear). If key missing, return `{}` and log a warning (fail-open to Anthropic is safer than a broken spawn — but the credit path will still catch a real 401).
- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `feat(provider): per-spawn resolve_harness_env with isolation guard`.

### Task 7: Thread provider into both CLI spawn paths

**Files:**
- Modify: `src/runner_utils.py` (`_claude_cli_complete`, `stream_claude_with_telemetry`, `make_clean_env` allowlist)
- Test: `tests/test_llm_provider.py`, `tests/test_subprocess_util.py`

**Interfaces:**
- Consumes: `resolve_harness_env`.
- Produces: both spawn functions accept `provider: str = "claude"` and merge `resolve_harness_env` into the spawn env; `make_clean_env` passes through `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN`.

- [ ] **Step 1: Write failing test** — capture the env a spawn would use.

```python
async def test_claude_cli_spawn_env_carries_zai_override(monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", "sk-zai-test")
    captured = {}
    class FakeRunner:
        async def run_simple(self, cmd, env, input, timeout):
            captured.update(env)
            from execution import SimpleResult
            return SimpleResult(stdout="ok", returncode=0)
    from runner_utils import _claude_cli_complete
    from config import HydraFlowConfig
    await _claude_cli_complete(runner=FakeRunner(), tool="claude", model="glm-5.2",
        prompt="p", timeout=1, gh_token="", isolate_user_settings=True,
        provider="zai", config=HydraFlowConfig())
    assert captured["ANTHROPIC_BASE_URL"].endswith("/api/anthropic")
    assert captured["ANTHROPIC_AUTH_TOKEN"] == "sk-zai-test"
```

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** — add `provider`/`config` params; `env = make_clean_env(gh_token); env.update(resolve_harness_env(provider, config))`; add the two ANTHROPIC vars to `make_clean_env`'s allowlist. Update every caller to pass the role's provider (default `"claude"` keeps existing behavior).
- [ ] **Step 4: Run — expect PASS**; run `tests/test_subprocess_util.py` to confirm allowlist change is green.
- [ ] **Step 5: Commit** — `feat(provider): thread provider through claude CLI spawn paths`.

---

## Phase D — Credit scoping + detection fidelity

### Task 8: Tag CreditExhaustedError with provider on the CLI path

**Files:**
- Modify: `src/runner_utils.py` (`raise_if_credit_exhausted` signature + streaming `_post_stream_result` check)
- Test: `tests/test_per_backend_credit_pause.py`, `tests/regressions/test_issue_9807_per_backend_credit_isolation.py`

**Interfaces:**
- Produces: `raise_if_credit_exhausted(stdout, stderr, tool, provider="claude")` raising `CreditExhaustedError(provider=normalize_provider(provider))`.

- [ ] **Step 1: Write failing test.**

```python
def test_cli_credit_out_tags_zai_provider():
    from runner_utils import raise_if_credit_exhausted
    from subprocess_util import CreditExhaustedError
    with pytest.raises(CreditExhaustedError) as ei:
        raise_if_credit_exhausted("credit balance is too low", "", "claude", provider="zai")
    assert ei.value.provider == "zai"

def test_cli_credit_out_defaults_anthropic():
    from runner_utils import raise_if_credit_exhausted
    from subprocess_util import CreditExhaustedError
    with pytest.raises(CreditExhaustedError) as ei:
        raise_if_credit_exhausted("usage limit reached", "", "claude")
    assert ei.value.provider == "anthropic"
```

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** — add `provider` param; pass `provider=normalize_provider(provider)` into `CreditExhaustedError`; thread the provider from the spawn callers (Task 7) into both the lightweight and streaming credit checks.
- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `fix(credit): tag CLI-path CreditExhaustedError with resolved provider`.

### Task 9: z.ai credit-string detection + orchestrator loop→provider map

**Files:**
- Modify: `src/subprocess_util.py` (`is_credit_exhaustion` — add z.ai/anthropic-compat patterns)
- Modify: `src/orchestrator.py` (extend the loop→provider dial map to agentic loops)
- Create: `tests/fixtures/zai_credit_stderr.txt` (cassette of the real GLM 429/quota stderr)
- Test: `tests/test_subprocess_util.py`, `tests/test_control_routes_settings.py`

**Interfaces:**
- Consumes: Task 8's provider tagging.
- Produces: `is_credit_exhaustion()` returns True for GLM quota stderr; orchestrator maps each agentic loop to its `*_provider` dial.

- [ ] **Step 1: Write failing test.**

```python
def test_is_credit_exhaustion_detects_zai_quota():
    from subprocess_util import is_credit_exhaustion
    body = open("tests/fixtures/zai_credit_stderr.txt").read()
    assert is_credit_exhaustion(body) is True
```

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** — capture the real GLM stderr shape into the fixture; add its distinguishing phrases (e.g. `insufficient balance`, `quota`, HTTP `402`/`429` markers) to `_CREDIT_PATTERNS`; extend the orchestrator's provider map so agentic loops routed to zai are scoped by the existing per-provider pause.
- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `fix(credit): detect z.ai quota stderr + scope agentic loops per provider`.

---

## Phase E — Telemetry attribution

### Task 10: Attribute agentic-on-z.ai spend to zai

**Files:**
- Modify: `src/runner_utils.py` (`_telemetry_cmd`/record path — head=provider when on a harness backend)
- Test: `tests/test_model_pricing.py` or `tests/test_llm_provider.py`

**Interfaces:**
- Produces: telemetry `tool`/provider column reads `zai` for agentic-on-z.ai spawns.

- [ ] **Step 1: Write failing test** — a zai-harness spawn records provider `zai`, not `anthropic`.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** — when `resolve_harness_env` is non-empty (harness on a non-Anthropic backend), set the telemetry head to the provider, mirroring the one-shot path.
- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `feat(telemetry): attribute agentic z.ai spend to the zai backend`.

---

## Phase F — Full test pyramid (MockWorld + sandbox + regression)

### Task 11: MockWorld scenario — GLM cap pauses only z.ai loops

**Files:**
- Create: `tests/scenarios/test_zai_credit_scoping_mockworld.py`
- Test: itself

- [ ] **Step 1: Write the scenario** — configure a maintenance loop `provider=zai`; inject a GLM 429; assert only zai-routed loops pause and implement/review keep running.
- [ ] **Step 2: Run — expect FAIL** (until wiring holds).
- [ ] **Step 3: Adjust wiring if needed** (should pass on Phase D work).
- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `test(scenario): GLM cap scopes pause to z.ai loops only`.

### Task 12: Sandbox e2e — docker spawn gets the override; main workers don't

**Files:**
- Create: `tests/sandbox_scenarios/scenarios/s5X_zai_harness_routing.py` (next free id)
- Modify: sandbox env allowlist to pass `ZAI_API_KEY` + `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN`
- Test: itself

- [ ] **Step 1: Write scenario** — agentic maintenance loop `provider=zai` → its docker spawn env carries `ANTHROPIC_BASE_URL` (fake z.ai endpoint) and completes; a `provider=claude` work spawn carries no override.
- [ ] **Step 2–4: RED → wire → GREEN.**
- [ ] **Step 5: Commit** — `test(sandbox): z.ai harness routing e2e + isolation assertion`.

---

## Phase G — ADR + arch-regen

### Task 13: ADR + regenerate arch artifacts

**Files:**
- Create: `docs/adr/00NN-provider-harness-backend-split.md` (next free number)
- Modify: `docs/adr/README.md` (index row)
- Modify: `docs/arch/.meta.json`, `docs/arch/generated/*` (via `make arch-regen`)

- [ ] **Step 1:** Write the ADR (Accepted) superseding the "agentic path stays on Claude" assumption; record the two-faced z.ai registry, per-spawn isolation, per-provider credit scoping, `claude`+`codex`-only tool axis. Add `Enforced by:` referencing the isolation + credit tests.
- [ ] **Step 2:** Add the README index row.
- [ ] **Step 3:** Run `make arch-regen`; commit the artifact delta.
- [ ] **Step 4:** `make quality` (full — not a subset).
- [ ] **Step 5: Commit** — `docs(adr): provider/harness backend split (supersedes agentic=Claude-only)`.

---

## Final: quality gate + PR

- [ ] `make quality` green (full suite; backend-removal blast radius).
- [ ] `make arch-regen` clean (no drift).
- [ ] Push; `gh pr create --base staging`.
- [ ] 2–3 fresh-eyes review iterations to convergence (ADR-0051).
