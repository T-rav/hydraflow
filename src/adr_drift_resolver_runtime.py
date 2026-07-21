"""Production LLM adapter for AdrDriftResolverLoop (#9976).

``AdrDriftResolverLLMClient`` implements ``adr_drift_triage_llm.LLMClient``
by routing through ``runner_utils.run_lightweight_agent`` — the same
telemetried, CH-6-gated, credit-aware one-shot spawn seam
``term_proposer_runtime.ClaudeCLIClient`` uses for the term-proposer /
entry-evidence drafters. Not a reuse of ``ClaudeCLIClient`` itself: this
call site has a GitHub issue in scope (the rollup being triaged) and
threads ``issue_number``/``issue_labels`` through on every call, which
``ClaudeCLIClient``'s Protocol shape doesn't carry (see
``adr_drift_triage_llm.py``'s module docstring for why that's a distinct
Protocol rather than a widened shared one).

Wired into ``service_registry.build_services`` (production); MockWorld
scenarios and unit tests inject a stub implementing the same Protocol
instead — see ``tests/scenarios/catalog/loop_registrations.py``.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from agent_cli import AgentTool
from runner_utils import run_lightweight_agent

logger = logging.getLogger("hydraflow.adr_drift_resolver_runtime")

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from execution import SubprocessRunner


class AdrDriftResolverLLMClient:
    """Subprocess adapter for ``adr_drift_triage_llm.LLMClient``.

    Routes the TRIAGE call through ``runner_utils.run_lightweight_agent``
    (the shared no-tools seam) so the spawn is gated (CH-6), telemetried
    (spend hits the cost cap), and credit-exhaustion aware — and so the
    backend follows the ``adr_drift_resolver_provider`` dial (``claude``
    CLI, or ``openrouter``/``zai``/``kimi`` over an OpenAI-compatible
    endpoint). Parses JSON out of the reply, tolerant of markdown fences.
    """

    def __init__(
        self,
        runner: SubprocessRunner,
        config: HydraFlowConfig,
        *,
        tool: AgentTool = "claude",
        model: str = "sonnet",
        timeout: int = 180,
        provider: str = "claude",
        source: str = "adr_drift_resolver",
    ) -> None:
        self._runner = runner
        self._config = config
        self._tool: AgentTool = tool
        self._model = model
        self._timeout = timeout
        self._provider = provider
        self._source = source

    async def complete_structured(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
        issue_number: int,
        issue_labels: list[str],
    ) -> dict[str, Any]:
        """Send *prompt* through the one-shot seam and return the parsed JSON.

        ``issue_number``/``issue_labels`` feed the CH-6 gate's upward-only
        ``data-class:`` label elevation — this call site has a real GitHub
        issue in scope (the drift rollup being triaged), unlike the
        term-proposer's drafting call, so both are always threaded through.
        """

        result = await run_lightweight_agent(
            runner=self._runner,
            config=self._config,
            tool=self._tool,
            model=self._model,
            prompt=prompt,
            source=self._source,
            timeout=self._timeout,
            provider=self._provider,
            response_schema=schema,
            issue_number=issue_number,
            issue_labels=issue_labels,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"{self._provider}/{self._tool} triage failed "
                f"(rc={result.returncode}): {result.stderr[:200]}"
            )
        return self._extract_json(result.stdout)

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        """Pull a JSON object out of CLI stdout (tolerant of markdown fences)."""
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise RuntimeError(f"no JSON object in CLI output: {text[:200]}")
        return json.loads(match.group(0))
