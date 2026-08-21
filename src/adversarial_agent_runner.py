"""Subprocess-CLI adapter that satisfies the AgentLike Protocol.

The earlier-adversarial pipeline (AssumptionSurfacer, PlanCouncil,
DiscoveryCouncil, ShapeChallenger, ShapeExpertCouncil, SpecACGenerator,
SpecJudge) each take an agent satisfying the two-string-in,
JSON-string-out contract in :mod:`src.adversarial_agents`. This adapter
wraps the centralized one-shot execution seam
(:func:`runner_utils.run_lightweight_agent`) so the adversarial pipeline can
drive real agent subprocesses in production without bypassing prompt policy,
gateway routing, credit detection, or inference telemetry.

Design notes
------------

* The Claude/Codex/Gemini/Pi CLIs invoked through
  ``build_lightweight_command`` accept a single prompt argument; there
  is no separate ``system`` slot in the lightweight (non-streaming)
  path. We therefore concatenate ``system_prompt`` + ``user_message``
  with explicit section headers. The adversarial-stage system prompts
  already include the JSON output contract verbatim, so this preserves
  the contract end-to-end.

* The adapter returns raw stdout. Callers (AssumptionSurfacer, etc.)
  are responsible for JSON-parsing and turning malformed replies into
  soft outputs per the adversarial-pipeline contract.

* Dark-factory contract: ``CreditExhaustedError`` is reraised so the
  outer loop pauses on billing signal rather than burning attempt
  budget. ``reraise_on_credit_or_bug`` catches likely-bug exceptions
  (TypeError, KeyError, etc.) so they surface in logs instead of
  silently becoming an empty findings list.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent_cli import AgentTool
from runner_utils import run_lightweight_agent

if TYPE_CHECKING:
    from config import Credentials, HydraFlowConfig
    from execution import SubprocessRunner

logger = logging.getLogger("hydraflow.adversarial_agent_runner")


@dataclass
class SubprocessAgentRunner:
    """Subprocess-CLI adapter satisfying the AgentLike Protocol.

    Spawns a one-shot CLI process per ``run`` call. Stateless — a
    single instance is safe to share across all adversarial-stage
    agents (the per-call ``system_prompt`` is what differentiates a
    surfacer from a council voter).

    Attributes
    ----------
    runner:
        The :class:`execution.SubprocessRunner` used to invoke the CLI.
        Production paths inject the Docker runner; tests inject fakes.
    config:
        The active repository configuration. Required so this adapter follows
        the same prompt-policy, provider, gateway, and telemetry contracts as
        every other one-shot LLM spawn.
    tool:
        Which agent CLI to invoke. Defaults to ``"claude"``.
    model:
        Model identifier passed to the CLI. Defaults to Claude Haiku —
        the adversarial stages are critic-style and benefit from a
        fast, low-cost model.
    timeout:
        Per-call subprocess timeout in seconds. The adversarial stages
        are one-shot critics, not multi-turn agents, so the default is
        deliberately shorter than the planner/implement timeout.
    credentials:
        Optional :class:`config.Credentials`; when provided, the
        ``gh_token`` is passed to the centralized spawn seam.
    provider:
        Harness transport for these planning critics. Production wiring uses
        the planner's provider dial so the sub-spawns cannot escape its route.
    """

    runner: SubprocessRunner
    config: HydraFlowConfig
    tool: AgentTool = "claude"
    model: str = "claude-haiku-4-5-20251001"
    timeout: float = 180.0
    credentials: Credentials | None = None
    provider: str = "claude"

    async def run(self, system_prompt: str, user_message: str) -> str:
        """Send the prompts to the CLI and return raw stdout.

        Concatenates ``system_prompt`` + ``user_message`` into a single
        prompt with explicit section headers (the lightweight CLI path
        has no separate system slot). The downstream caller JSON-parses
        the result.

        Raises
        ------
        CreditExhaustedError:
            When the CLI output indicates API credit exhaustion, so the
            outer loop can pause on the billing signal rather than burn
            attempt budget.
        Exception:
            Any other ``except Exception`` is filtered through
            :func:`reraise_on_credit_or_bug` so likely bugs (TypeError,
            KeyError, etc.) surface in logs instead of becoming a soft
            empty reply.
        """
        prompt = self._compose_prompt(system_prompt, user_message)
        gh_token = self.credentials.gh_token if self.credentials is not None else ""
        result = await run_lightweight_agent(
            runner=self.runner,
            config=self.config,
            tool=self.tool,
            model=self.model,
            prompt=prompt,
            source="adversarial_planner",
            timeout=self.timeout,
            gh_token=gh_token,
            # Adversarial judges (SpecJudge, PlanCouncil, …) emit strict JSON.
            # Isolate from host user plugins/hooks that would derail the
            # machine-readable response contract.
            isolate_user_settings=True,
            provider=self.provider,
            # AgentLike's contract carries only the two prompt strings; it has
            # no Task/issue object from which to derive labels. The repository
            # data class is still enforced by the prompt gate.
            issue_labels=(),
        )

        stdout = result.stdout or ""
        stderr = result.stderr or ""

        if result.returncode != 0:
            # The CLI exited nonzero but it wasn't a credit-exhaustion
            # signal. Log + soft-fail: the AgentLike contract returns a
            # string and the caller will treat empty/non-JSON as an
            # empty findings list. This prevents one flaky voter from
            # crashing the whole adversarial stage.
            logger.warning(
                "SubprocessAgentRunner(%s) returned rc=%d: %s",
                self.tool,
                result.returncode,
                stderr[:200],
            )
            return ""

        return stdout

    @staticmethod
    def _compose_prompt(system_prompt: str, user_message: str) -> str:
        """Concatenate system + user into a single CLI prompt.

        Section headers are explicit so the model treats the system
        block as standing instructions and the user block as the
        message to evaluate. Matches the lightweight CLI's
        single-prompt convention used elsewhere
        (``term_proposer_runtime.ClaudeCLIClient``,
        ``adr_reviewer``, ``transcript_summarizer``).
        """
        return (
            "# System instructions\n"
            f"{system_prompt}\n\n"
            "# User message\n"
            f"{user_message}\n"
        )
