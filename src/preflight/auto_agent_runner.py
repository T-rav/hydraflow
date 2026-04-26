"""AutoAgentRunner — Claude Code subprocess spawn for AutoAgentPreflightLoop.

Wraps the standard `stream_claude_process` subprocess pattern with the
auto-agent-specific:

- tool restrictions (spec §5.2 — `--disallowedTools` flag carries the CLI
  restrictions; file-path restrictions are reinforced in the prompt envelope).
- prompt-hash + cost-capture for the `PreflightSpawn` return contract.
- telemetry recording so dashboard cost rollups include auto-agent runs
  alongside other phases (`source="auto_agent_preflight"`).

This module replaces the placeholder `_build_spawn_fn` in
`src/auto_agent_preflight_loop.py`. Tests for this module monkeypatch
`stream_claude_process` to avoid real subprocess invocation; the
end-to-end scenario tests still mock at the `_build_spawn_fn` layer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from agent_cli import build_agent_command
from config import HydraFlowConfig
from events import EventBus
from model_pricing import load_pricing
from preflight.agent import PreflightSpawn, hash_prompt
from prompt_telemetry import PromptTelemetry
from runner_utils import StreamConfig, stream_claude_process

logger = logging.getLogger("hydraflow.preflight.auto_agent_runner")


# Spec §5.2 — tools the auto-agent must NOT use.
#
# The Claude Code CLI's `--disallowedTools` flag enforces tool-name
# restrictions. File-path restrictions (no `.github/workflows/`, no
# secrets, no auto-agent self-modification, etc.) are enforced in the
# prompt envelope (`prompts/auto_agent/_envelope.md`) and rely on the
# agent honouring the constraint — there is no path-level CLI gate.
#
# `WebFetch` is disabled because the auto-agent should reason from the
# context the loop gathered (wiki + sentry + recent commits + escalation
# context), not chase arbitrary external URLs that could leak issue
# content or pull in malicious instructions.
_AUTO_AGENT_DISALLOWED_TOOLS = "WebFetch"


def _coerce_int(value: object) -> int:
    """Best-effort int coercion for usage_stats values from streaming parsers.

    Stream parsers may emit ints, strings, or even Decimal — coerce safely
    and clamp to >= 0 since negative token counts are nonsense.
    """
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


class AutoAgentRunner:
    """Spawns a Claude Code subprocess for one auto-agent attempt.

    One instance per attempt; lifetime is bounded by `run()`.
    """

    def __init__(self, *, config: HydraFlowConfig, event_bus: EventBus) -> None:
        self._config = config
        self._bus = event_bus
        self._active_procs: set[asyncio.subprocess.Process] = set()
        self._telemetry = PromptTelemetry(config)

    async def run(
        self,
        *,
        prompt: str,
        worktree_path: str,
        issue_number: int,
    ) -> PreflightSpawn:
        """Run one attempt; return a `PreflightSpawn` with cost + crash status.

        Never raises — any subprocess failure is collapsed into
        `PreflightSpawn(crashed=True, ...)` so the upstream PreflightAgent
        can map it to a `fatal` PreflightResult.
        """
        cmd = build_agent_command(
            tool=self._config.implementation_tool,
            model=self._config.model,
            disallowed_tools=_AUTO_AGENT_DISALLOWED_TOOLS,
        )
        usage_stats: dict[str, object] = {}
        prompt_hash = hash_prompt(prompt)
        # Wall-clock cap defaults to the loop-wide config; if the operator
        # has set `auto_agent_wall_clock_cap_s`, honour it as the subprocess
        # timeout. None → fall back to the codebase-wide `agent_timeout`.
        timeout_s = (
            self._config.auto_agent_wall_clock_cap_s or self._config.agent_timeout
        )
        start = time.monotonic()
        crashed = False
        transcript = ""
        try:
            transcript = await stream_claude_process(
                cmd=cmd,
                prompt=prompt,
                cwd=Path(worktree_path),
                active_procs=self._active_procs,
                event_bus=self._bus,
                event_data={
                    "issue": issue_number,
                    "source": "auto_agent_preflight",
                },
                logger=logger,
                config=StreamConfig(
                    timeout=timeout_s,
                    usage_stats=usage_stats,
                ),
            )
        except Exception as exc:
            crashed = True
            # Preserve any partial transcript captured before the failure
            # plus the exception message for the diagnosis comment.
            tail = transcript[-2000:] if transcript else ""
            transcript = f"{tail}\n\nspawn error: {exc}"
            logger.warning(
                "auto-agent subprocess failed for issue #%d: %s",
                issue_number,
                exc,
            )
        wall_s = time.monotonic() - start

        # Telemetry — best-effort write to the inferences.jsonl stream so
        # dashboard cost rollups include auto-agent attempts.
        try:
            self._telemetry.record(
                source="auto_agent_preflight",
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
            logger.warning("auto-agent telemetry write failed: %s", exc)

        cost_usd = self._estimate_cost(usage_stats)
        tokens = _coerce_int(usage_stats.get("total_tokens"))

        return PreflightSpawn(
            process=None,
            output_text=transcript,
            cost_usd=cost_usd,
            tokens=tokens,
            crashed=crashed,
            prompt_hash=prompt_hash,
        )

    def _estimate_cost(self, usage_stats: dict[str, object]) -> float:
        """Best-effort cost estimate from the usage_stats the parser populated.

        Returns 0.0 when the model isn't in the pricing table or stats are
        missing — avoids breaking the loop on a pricing-table miss.
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
            logger.warning("auto-agent cost estimate failed: %s", exc)
            return 0.0
