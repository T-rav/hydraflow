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
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from config import HydraFlowConfig
from events import EventBus
from model_pricing import load_pricing
from prompt_telemetry import PromptTelemetry

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

    def _estimate_cost(self, usage_stats: dict[str, object]) -> float:
        """Default cost estimate via model_pricing.

        Returns 0.0 when the model isn't in the pricing table or stats are
        missing. Subclasses may override for custom pricing or no-op for
        free-tier runs.
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
            return float(estimate or 0.0)
        except Exception as exc:
            logger.warning("subprocess runner cost estimate failed: %s", exc)
            return 0.0
