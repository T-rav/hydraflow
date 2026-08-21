"""BaseSubprocessRunner — abstract base for runners that spawn a subprocess.

Spec §3.1. Encapsulates the four conventions PR #8439 surfaced as
load-bearing across any runner that spawns a Claude Code / codex /
gemini subprocess:

- 3-attempt auth-retry loop with exponential backoff (5s, 10s, 20s) on
  AuthenticationRetryError from runner_utils.
- reraise_on_credit_or_bug propagates CreditExhaustedError + terminal
  AuthenticationError so caretaker loops can suspend.
- PromptTelemetry.record() with subclass-provided source attribution.
- Never-raises contract: every failure path returns a typed result,
  never propagates a generic RuntimeError to the caller.

Subclasses parameterise their own typed result (e.g.,
`AutoAgentRunner(BaseSubprocessRunner[PreflightSpawn])`) — the base does
NOT impose a single shared dataclass. The internal `SpawnOutcome` is the
record passed from `base.run()` to `subclass._make_result`.
"""

from __future__ import annotations

import abc
import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from config import HydraFlowConfig
from credit_failover import apply_credit_failover
from events import EventBus
from exception_classify import reraise_on_credit_or_bug
from execution import get_default_runner
from model_pricing import input_includes_cache_for, load_pricing, usage_shape_for_tool
from prompt_gate import PromptGateBlockedError, gate_prompt
from prompt_telemetry import PromptTelemetry, parse_command_tool_model
from repo_backend import apply_repo_provider
from runner_utils import (
    AuthenticationRetryError,
    StreamConfig,
    _terminal_gateway_runner,
    harness_billing_provider,
    renew_gateway_key_if_needed,
    resolve_harness_env,
    revoke_gateway_key,
    stream_claude_process,
    telemetry_tool_for_transport,
)

logger = logging.getLogger("hydraflow.runners.base_subprocess_runner")


@dataclass(frozen=True)
class SpawnOutcome:
    """Internal record passed from base.run() to subclass._make_result.

    Internal to BaseSubprocessRunner — not part of any subclass's public
    API. Subclass converts this into its own dataclass (e.g., PreflightSpawn)
    via _make_result.
    """

    transcript: str
    usage_stats: dict[str, object]
    wall_clock_s: float
    crashed: bool
    prompt_hash: str
    cost_usd: float
    cost_unknown: bool = False


def _coerce_int(value: object) -> int:
    """Best-effort int coercion for usage_stats values from streaming parsers.

    Stream parsers may emit ints, strings, or even Decimal — coerce safely
    and clamp to >= 0 since negative token counts are nonsense.
    """
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


T_Result = TypeVar("T_Result")


class BaseSubprocessRunner(abc.ABC, Generic[T_Result]):
    """Abstract base for subprocess-spawning runners. See module docstring.

    Subclasses MUST override:
    - `_telemetry_source()` → str (e.g., "auto_agent_preflight")
    - `_build_command(prompt, worktree)` → list[str]
    - `_make_result(outcome)` → T_Result (e.g., PreflightSpawn)

    Subclasses MAY override:
    - `_default_timeout_s()` → int (default: config.agent_timeout)
    - `_pre_spawn_hook(prompt)` → None (logging, validation, etc.)
    - `_estimate_cost(usage_stats, usage_shape=...)` → float (default: model_pricing lookup)
    """

    # Match BaseRunner._execute auth-retry budget so transient OAuth blips
    # don't burn the per-issue attempt cap.
    _AUTH_RETRY_MAX = 3
    _AUTH_RETRY_BASE_DELAY = 5.0  # seconds

    def __init__(self, *, config: HydraFlowConfig, event_bus: EventBus) -> None:
        self._config = config
        self._bus = event_bus
        self._active_procs: set[asyncio.subprocess.Process] = set()
        self._telemetry = PromptTelemetry(config)

    @abc.abstractmethod
    def _telemetry_source(self) -> str:
        """Return the source string for PromptTelemetry attribution."""

    @abc.abstractmethod
    def _build_command(self, prompt: str, worktree: Path) -> list[str]:
        """Build the CLI command (e.g., via build_agent_command)."""

    @abc.abstractmethod
    def _make_result(self, outcome: SpawnOutcome) -> T_Result:
        """Convert the internal SpawnOutcome into the subclass's typed result."""

    def _default_timeout_s(self) -> int:
        """Default subprocess timeout. Override per subclass for caps."""
        return int(self._config.agent_timeout)

    def _pre_spawn_hook(self, prompt: str) -> None:
        """Hook for pre-spawn checks/logging (e.g., warn on backend mismatch)."""
        # Default: no-op.

    def _estimate_cost(
        self, usage_stats: dict[str, object], *, usage_shape: str | None = None
    ) -> float | None:
        """Default cost estimate via model_pricing.

        Returns ``None`` when the model isn't in the pricing table (or the
        lookup fails) — the caller records the spend as UNKNOWN rather than
        silently folding it into $0 (#9821). Subclasses may override for
        custom pricing or no-op for free-tier runs.

        ``usage_shape`` is how the CLI produced the counts (see
        :func:`model_pricing.usage_shape_for_tool`); a Claude CLI spawn is
        Anthropic-shaped (cache excluded) even when credit failover routes it
        to a GLM model whose one-shot table flag is cache-inclusive.
        """
        try:
            pricing = load_pricing()
            estimate = pricing.estimate_cost(
                model=self._config.model,
                input_tokens=_coerce_int(usage_stats.get("input_tokens")),
                output_tokens=_coerce_int(usage_stats.get("output_tokens")),
                cache_write_tokens=_coerce_int(
                    usage_stats.get("cache_creation_input_tokens")
                ),
                cache_read_tokens=_coerce_int(
                    usage_stats.get("cache_read_input_tokens")
                ),
                input_includes_cache=input_includes_cache_for(usage_shape),
            )
            return float(estimate) if estimate is not None else None
        except Exception as exc:
            logger.warning("subprocess runner cost estimate failed: %s", exc)
            return None

    async def run(
        self,
        *,
        prompt: str,
        worktree_path: str,
        issue_number: int,
    ) -> T_Result:
        """Run one subprocess attempt; never raises.

        Auth blips retry up to _AUTH_RETRY_MAX times. Credit/auth-terminal
        errors propagate (caretaker loop suspends). Other failures collapse
        to crashed=True in the SpawnOutcome the subclass converts.
        """
        from preflight.agent import hash_prompt  # noqa: PLC0415

        # CH-6 data-governance gate (#9734): redact/block BEFORE spawn. The
        # gated tool mirrors this seam's telemetry attribution
        # (config.implementation_tool). A regulated-class block collapses to
        # this seam's never-raises contract as a crashed outcome — the prompt
        # was never sent (fail closed) and the gate wrote the audit record.
        try:
            gated = gate_prompt(
                prompt,
                config=self._config,
                source=self._telemetry_source(),
                tool=self._config.implementation_tool,
                issue_number=issue_number,
            )
        except PromptGateBlockedError as exc:
            return self._make_result(
                SpawnOutcome(
                    transcript=str(exc),
                    usage_stats={},
                    wall_clock_s=0.0,
                    crashed=True,
                    prompt_hash=hash_prompt(prompt),
                    cost_usd=0.0,
                )
            )
        prompt = gated.prompt

        self._pre_spawn_hook(prompt)
        cmd = self._build_command(prompt, Path(worktree_path))
        initial_provider = "claude"
        cmd_tool, _ = parse_command_tool_model(cmd)
        if (
            getattr(self._config, "gateway_fleet_ratchet_enabled", False) is True
            and cmd_tool == "claude"
        ):
            initial_provider = "gateway"
        # Repo-wide backend override (#11211): these runners have no provider
        # dial of their own (always native Claude), so config.repo_provider is
        # the only lever routing this seam's spawns to GLM. No-op unless
        # repo_provider == "zai" and ZAI_API_KEY is present.
        provider, cmd = apply_repo_provider(initial_provider, cmd, self._config)
        # Credit failover (#10844): these runners always spawn on native Claude
        # (no provider dial), so without this a Claude cap would crash-loop the
        # loop instead of failing over. Reroute the spawn to GLM while failover
        # is active, mirroring base_runner._execute. No-op otherwise.
        provider, cmd = apply_credit_failover(provider, cmd, self._config)
        _, resolved_model = parse_command_tool_model(cmd)
        timeout_s = self._default_timeout_s()
        try:
            harness_env = await resolve_harness_env(
                provider,
                self._config,
                model=resolved_model,
                source=self._telemetry_source(),
                session_id=getattr(self._bus, "current_session_id", None),
                timeout_seconds=timeout_s,
                issue_number=issue_number,
            )
        except Exception as exc:
            # A failed gateway mint is a pre-spawn crash, never permission to
            # fall through to a direct credential.  Preserve this base class's
            # never-raises contract for infrastructure failures.
            reraise_on_credit_or_bug(exc)
            return self._make_result(
                SpawnOutcome(
                    transcript=f"gateway routing error: {exc}",
                    usage_stats={},
                    wall_clock_s=0.0,
                    crashed=True,
                    prompt_hash=hash_prompt(prompt),
                    cost_usd=0.0,
                )
            )
        billing_provider = harness_billing_provider(provider, resolved_model)

        usage_stats: dict[str, object] = {}
        prompt_hash = hash_prompt(prompt)
        start = time.monotonic()
        crashed = False
        transcript = ""

        last_auth_error: AuthenticationRetryError | None = None
        spawn_runner = get_default_runner()
        owned_runner = None
        runner_resolved = False
        try:
            for attempt in range(1, self._AUTH_RETRY_MAX + 1):
                try:
                    if not runner_resolved:
                        spawn_runner, owned_runner = _terminal_gateway_runner(
                            spawn_runner,
                            self._config,
                            provider,
                        )
                        runner_resolved = True
                    transcript = await stream_claude_process(
                        cmd=cmd,
                        prompt=prompt,
                        cwd=Path(worktree_path),
                        active_procs=self._active_procs,
                        event_bus=self._bus,
                        event_data={
                            "issue": issue_number,
                            "source": self._telemetry_source(),
                        },
                        logger=logger,
                        config=StreamConfig(
                            timeout=timeout_s,
                            runner=spawn_runner,
                            usage_stats=usage_stats,
                            harness_env=harness_env,
                            harness_transport=provider,
                            provider=billing_provider,
                        ),
                    )
                    last_auth_error = None
                    break
                except AuthenticationRetryError as exc:
                    last_auth_error = exc
                    if attempt < self._AUTH_RETRY_MAX:
                        delay = self._AUTH_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                        logger.warning(
                            "subprocess runner auth retry %d/%d for issue #%d, "
                            "sleeping %.0fs: %s",
                            attempt,
                            self._AUTH_RETRY_MAX,
                            issue_number,
                            delay,
                            exc,
                        )
                        await asyncio.sleep(delay)
                        await renew_gateway_key_if_needed(
                            harness_env,
                            min_validity_seconds=timeout_s,
                        )
                except Exception as exc:
                    # Credit / terminal-auth / programming bugs propagate so the
                    # caretaker loop can suspend or surface the bug; everything
                    # else collapses to crashed=True with a partial transcript.
                    reraise_on_credit_or_bug(exc)
                    crashed = True
                    tail = transcript[-2000:] if transcript else ""
                    transcript = f"{tail}\n\nspawn error: {exc}"
                    logger.warning(
                        "subprocess runner failed for issue #%d: %s",
                        issue_number,
                        exc,
                    )
                    break
        finally:
            try:
                await revoke_gateway_key(harness_env)
            finally:
                if owned_runner is not None:
                    await owned_runner.cleanup()

        if last_auth_error is not None:
            crashed = True
            transcript = (
                f"{transcript}\n\nauth retry exhausted after "
                f"{self._AUTH_RETRY_MAX} attempts: {last_auth_error}"
            )
            logger.error(
                "subprocess runner auth retry exhausted for issue #%d after %d attempts",
                issue_number,
                self._AUTH_RETRY_MAX,
            )
        wall_s = time.monotonic() - start

        # Shape of the usage counts follows the CLI that ran (``cmd_tool``),
        # never the transport marker stamped on ``tool`` below.
        usage_shape = usage_shape_for_tool(cmd_tool)
        # Telemetry — best-effort write to inferences.jsonl.
        try:
            self._telemetry.record(
                source=self._telemetry_source(),
                tool=telemetry_tool_for_transport(
                    provider, self._config.implementation_tool
                ),
                model=resolved_model,
                issue_number=issue_number,
                pr_number=None,
                session_id=self._bus.current_session_id,
                prompt_chars=len(prompt),
                transcript_chars=len(transcript),
                duration_seconds=wall_s,
                success=not crashed,
                stats=usage_stats,
                usage_shape=usage_shape,
            )
        except Exception as exc:
            logger.warning("subprocess runner telemetry write failed: %s", exc)

        estimate = self._estimate_cost(usage_stats, usage_shape=usage_shape)
        # Caps/sums stay numeric on 0.0; the FLAG carries honesty to
        # display surfaces (#9821).
        cost_usd = estimate if estimate is not None else 0.0
        cost_unknown = estimate is None

        outcome = SpawnOutcome(
            transcript=transcript,
            usage_stats=usage_stats,
            wall_clock_s=wall_s,
            crashed=crashed,
            prompt_hash=prompt_hash,
            cost_usd=cost_usd,
            cost_unknown=cost_unknown,
        )
        return self._make_result(outcome)
