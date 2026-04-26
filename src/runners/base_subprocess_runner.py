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

import logging
from dataclasses import dataclass

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
