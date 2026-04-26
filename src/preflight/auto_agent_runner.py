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
from exception_classify import reraise_on_credit_or_bug
from model_pricing import load_pricing
from preflight.agent import PreflightSpawn, hash_prompt
from prompt_telemetry import PromptTelemetry
from runner_utils import AuthenticationRetryError, StreamConfig, stream_claude_process

logger = logging.getLogger("hydraflow.preflight.auto_agent_runner")


# Match BaseRunner's auth-retry budget so transient OAuth blips don't burn
# the per-issue attempt cap. Three tries with exponential backoff: 5s, 10s, 20s.
_AUTH_RETRY_MAX = 3
_AUTH_RETRY_BASE_DELAY = 5.0  # seconds


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
        # `--disallowedTools=WebFetch` is silently dropped by build_agent_command
        # for codex/gemini backends (they don't take that flag). Warn so the
        # operator knows the CLI-level guard isn't active for that backend —
        # the path-level honor-system in the prompt envelope is the only
        # remaining restriction layer.
        if self._config.implementation_tool != "claude":
            logger.warning(
                "auto-agent: --disallowedTools is only enforced for the claude "
                "backend; current implementation_tool=%s — WebFetch restriction "
                "is honor-system + post-hoc CI for this run",
                self._config.implementation_tool,
            )

        cmd = build_agent_command(
            tool=self._config.implementation_tool,
            model=self._config.model,
            disallowed_tools=_AUTO_AGENT_DISALLOWED_TOOLS,
        )
        usage_stats: dict[str, object] = {}
        prompt_hash = hash_prompt(prompt)
        timeout_s = (
            self._config.auto_agent_wall_clock_cap_s or self._config.agent_timeout
        )
        start = time.monotonic()
        crashed = False
        transcript = ""

        # Auth-retry loop — mirrors BaseRunner._execute. AuthenticationRetryError
        # is a transient OAuth blip; retry up to _AUTH_RETRY_MAX times with
        # exponential backoff before giving up. CreditExhaustedError and
        # AuthenticationError (terminal) propagate via reraise_on_credit_or_bug
        # so the caretaker loop's outer handler can suspend ticking.
        last_auth_error: AuthenticationRetryError | None = None
        for attempt in range(1, _AUTH_RETRY_MAX + 1):
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
                last_auth_error = None
                break
            except AuthenticationRetryError as exc:
                last_auth_error = exc
                if attempt < _AUTH_RETRY_MAX:
                    delay = _AUTH_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        "auto-agent auth retry %d/%d for issue #%d, sleeping %.0fs: %s",
                        attempt,
                        _AUTH_RETRY_MAX,
                        issue_number,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
            except Exception as exc:
                # Credit exhaustion / terminal auth / programming bugs propagate
                # so the loop can suspend or surface the bug; everything else
                # collapses to crashed=True with a partial transcript.
                reraise_on_credit_or_bug(exc)
                crashed = True
                tail = transcript[-2000:] if transcript else ""
                transcript = f"{tail}\n\nspawn error: {exc}"
                logger.warning(
                    "auto-agent subprocess failed for issue #%d: %s",
                    issue_number,
                    exc,
                )
                break

        if last_auth_error is not None:
            crashed = True
            transcript = (
                f"{transcript}\n\nauth retry exhausted after "
                f"{_AUTH_RETRY_MAX} attempts: {last_auth_error}"
            )
            logger.error(
                "auto-agent auth retry exhausted for issue #%d after %d attempts",
                issue_number,
                _AUTH_RETRY_MAX,
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
