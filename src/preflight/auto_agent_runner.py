"""AutoAgentRunner — Claude Code subprocess spawn for AutoAgentPreflightLoop.

Spec §3.1 / ADR-0050. Inherits BaseSubprocessRunner[PreflightSpawn] for
the load-bearing conventions (auth-retry, reraise_on_credit_or_bug,
telemetry, never-raises). Auto-agent-specific concerns:

- restricted-mode hardening (ADR-0084): the auto-agent runs on
  attacker-reachable input (issue body/comments, sentry, wiki), so its
  command is built with ``restricted=True`` by default — claude drops
  ``bypassPermissions`` for ``acceptEdits`` + an explicit tool allowlist and
  disallows the WebFetch/WebSearch egress tools; codex switches to its
  network-blocked ``workspace-write`` sandbox. The ``agent_unrestricted_tools``
  escape hatch reverts to the legacy unrestricted mode.
- backend-mismatch warning when implementation_tool not in ("claude", "codex")
- wall-clock cap override (auto_agent_wall_clock_cap_s)
- result shape: PreflightSpawn (with output_text + tokens fields)
"""

from __future__ import annotations

import logging
from pathlib import Path

from agent_cli import build_agent_command
from preflight.agent import PreflightSpawn
from runners.base_subprocess_runner import (
    BaseSubprocessRunner,
    SpawnOutcome,
    _coerce_int,
)

logger = logging.getLogger("hydraflow.preflight.auto_agent_runner")


# Spec §5.2 / ADR-0084 — tools the auto-agent must NOT use.
#
# `WebFetch` (and, in restricted mode, `WebSearch`) are disabled because the
# auto-agent should reason from the context the loop gathered (wiki + sentry +
# recent commits + escalation context), not chase arbitrary external URLs that
# could leak issue content or pull in malicious instructions. In restricted
# mode build_agent_command additionally unions the egress tools
# (WebFetch/WebSearch) onto the disallow list, so this constant is the
# auto-agent-specific extra rather than the whole egress guard.
_AUTO_AGENT_DISALLOWED_TOOLS = "WebFetch"


class AutoAgentRunner(BaseSubprocessRunner[PreflightSpawn]):
    """Spawns a Claude Code subprocess for one auto-agent attempt.

    One instance per attempt; lifetime is bounded by `run()`.
    """

    def _telemetry_source(self) -> str:
        return "auto_agent_preflight"

    def _build_command(self, prompt: str, worktree: Path) -> list[str]:
        # The auto-agent operates on attacker-reachable input, so it MUST be
        # hardened by default (ADR-0084): restricted=True drops bypassPermissions
        # for acceptEdits + a tool allowlist (claude) / the network-blocked
        # workspace-write sandbox (codex). agent_unrestricted_tools is the
        # operator escape hatch back to the legacy unrestricted mode.
        return build_agent_command(
            tool=self._config.implementation_tool,
            model=self._config.model,
            disallowed_tools=_AUTO_AGENT_DISALLOWED_TOOLS,
            restricted=not self._config.agent_unrestricted_tools,
        )

    def _default_timeout_s(self) -> int:
        return int(
            self._config.auto_agent_wall_clock_cap_s or self._config.agent_timeout
        )

    def _pre_spawn_hook(self, prompt: str) -> None:
        # The claude backend gets the full restricted hardening (acceptEdits +
        # tool allowlist + WebFetch/WebSearch disallow). codex gets a real
        # network-egress block via its workspace-write sandbox. Other backends
        # (e.g. gemini) have no CLI-level allow/disallow surface, so restricted
        # mode is a no-op there and only the prompt-envelope honor-system +
        # post-hoc CI restrain egress. Warn so the operator knows.
        if self._config.implementation_tool not in ("claude", "codex"):
            logger.warning(
                "auto-agent: restricted-mode tool hardening (ADR-0084) is only "
                "CLI-enforced for the claude/codex backends; current "
                "implementation_tool=%s — egress restriction is honor-system + "
                "post-hoc CI for this run",
                self._config.implementation_tool,
            )

    def _make_result(self, outcome: SpawnOutcome) -> PreflightSpawn:
        return PreflightSpawn(
            process=None,
            output_text=outcome.transcript,
            cost_usd=outcome.cost_usd,
            tokens=_coerce_int(outcome.usage_stats.get("total_tokens")),
            crashed=outcome.crashed,
            prompt_hash=outcome.prompt_hash,
        )
