"""GoalSupervisorRunner — Fable subprocess spawn for the Tier-2 supervisor.

Inherits :class:`BaseSubprocessRunner` for the load-bearing conventions
(auth-retry, ``reraise_on_credit_or_bug``, telemetry, never-raises) and spawns
a **Fable** agent (``claude-fable-5``, ADR-0124) that reads the read-only health
snapshot and returns a structured :class:`SupervisorVerdict`.

Supervisor-specific concerns:

- **Fable model** — the command uses ``config.goal_supervisor_model``
  (default ``claude-fable-5``), a Claude model, so ``tool="claude"`` is pinned.
- **Isolated settings** — ``isolate_user_settings=True`` keeps the spawn on the
  project ``--setting-sources`` so a host ``SessionStart`` hook can't derail the
  JSON verdict contract (same discipline triage/judges use).
- **Restricted** — the supervisor only needs to reason over the snapshot text;
  it runs restricted (no WebFetch/WebSearch egress).
- **Bounded** — a supervisor tick wants a quick verdict, not a long agentic run,
  so the subprocess timeout is capped.
- **Cost attribution** — cost estimates use the Fable model so per-loop spend
  attributes to ``claude-fable-5``, not the factory's implementation model.
"""

from __future__ import annotations

import logging
from pathlib import Path

from agent_cli import build_agent_command
from model_pricing import input_includes_cache_for, load_pricing
from runners.base_subprocess_runner import (
    BaseSubprocessRunner,
    SpawnOutcome,
    _coerce_int,
)
from supervisor_observation import SupervisorVerdict, parse_supervisor_verdict

logger = logging.getLogger("hydraflow.goal_supervisor_runner")

#: Cap a supervisor spawn — a liveness verdict should be quick, not a long run.
_SUPERVISOR_TIMEOUT_CAP_S = 300


class GoalSupervisorRunner(BaseSubprocessRunner[SupervisorVerdict]):
    """Spawns a Fable subprocess for one supervisor tick.

    One instance is reused across ticks; ``run()`` bounds each spawn.
    """

    def _telemetry_source(self) -> str:
        return "goal_supervisor"

    def _build_command(self, prompt: str, worktree: Path) -> list[str]:
        # Fable is a ``claude-*`` model, so the tool is pinned to "claude".
        # isolate_user_settings keeps the JSON-verdict contract intact.
        return build_agent_command(
            tool="claude",
            model=self._config.goal_supervisor_model,
            restricted=True,
            isolate_user_settings=True,
        )

    def _default_timeout_s(self) -> int:
        return min(int(self._config.agent_timeout), _SUPERVISOR_TIMEOUT_CAP_S)

    def _make_result(self, outcome: SpawnOutcome) -> SupervisorVerdict:
        # A crashed/empty transcript parses to a truthful "(no parseable verdict)"
        # rather than a fabricated resolution (honest-thread contract, rule 6).
        return parse_supervisor_verdict(outcome.transcript)

    def _estimate_cost(
        self, usage_stats: dict[str, object], *, usage_shape: str | None = None
    ) -> float | None:
        # Attribute spend to the Fable model (not config.model) so per-loop cost
        # rollups are honest.
        try:
            pricing = load_pricing()
            estimate = pricing.estimate_cost(
                model=self._config.goal_supervisor_model,
                input_tokens=_coerce_int(usage_stats.get("input_tokens")),
                output_tokens=_coerce_int(usage_stats.get("output_tokens")),
                cache_write_tokens=_coerce_int(
                    usage_stats.get("cache_creation_input_tokens")
                ),
                cache_read_tokens=_coerce_int(
                    usage_stats.get("cache_read_input_tokens")
                ),
                # The supervisor always runs on the Claude CLI (tool pinned to
                # "claude"): Anthropic-shaped usage, cache excluded from input.
                input_includes_cache=input_includes_cache_for(usage_shape, "claude"),
            )
            return float(estimate) if estimate is not None else None
        except Exception as exc:  # noqa: BLE001
            # Cost is best-effort telemetry; a pricing miss must not fail the run.
            logger.warning("goal-supervisor cost estimate failed: %s", exc)
            return None
