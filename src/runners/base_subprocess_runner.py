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
from model_pricing import load_pricing
from prompt_gate import PromptGateBlockedError, gate_prompt
from prompt_telemetry import PromptTelemetry
from repo_backend import apply_repo_provider
from runner_utils import (
    AuthenticationRetryError,
    StreamConfig,
    resolve_harness_env,
    stream_claude_process,
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
    - `_estimate_cost(usage_stats)` → float (default: model_pricing lookup)
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

    def _estimate_cost(self, usage_stats: dict[str, object]) -> float | None:
        """Default cost estimate via model_pricing.

        Returns ``None`` when the model isn't in the pricing table (or the
        lookup fails) — the caller records the spend as UNKNOWN rather than
        silently folding it into $0 (#9821). Subclasses may override for
        custom pricing or no-op for free-tier runs.
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
        # Repo-wide backend override (#11211): these runners have no provider
        # dial of their own (always native Claude), so config.repo_provider is
        # the only lever routing this seam's spawns to GLM. No-op unless
        # repo_provider == "zai" and ZAI_API_KEY is present.
        provider, cmd = apply_repo_provider("claude", cmd, self._config)
        # Credit failover (#10844): these runners always spawn on native Claude
        # (no provider dial), so without this a Claude cap would crash-loop the
        # loop instead of failing over. Reroute the spawn to GLM while failover
        # is active, mirroring base_runner._execute. No-op otherwise.
        provider, cmd = apply_credit_failover(provider, cmd, self._config)
        harness_env = resolve_harness_env(provider, self._config)

        usage_stats: dict[str, object] = {}
        prompt_hash = hash_prompt(prompt)
        timeout_s = self._default_timeout_s()
        start = time.monotonic()
        crashed = False
        transcript = ""

        last_auth_error: AuthenticationRetryError | None = None
        for attempt in range(1, self._AUTH_RETRY_MAX + 1):
            try:
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
                        usage_stats=usage_stats,
                        harness_env=harness_env,
                        provider=provider,
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

        # Telemetry — best-effort write to inferences.jsonl.
        try:
            self._telemetry.record(
                source=self._telemetry_source(),
                tool=self._config.implementation_tool,
                model=self._config.model,
                issue_number=issue_number,
                pr_number=None,
                session_id=self._bus.current_session_id,
                prompt_chars=len(prompt),
                transcript_chars=len(transcript),
                duration_seconds=wall_s,
                success=not crashed,
                stats=usage_stats,
            )
        except Exception as exc:
            logger.warning("subprocess runner telemetry write failed: %s", exc)

        estimate = self._estimate_cost(usage_stats)
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
