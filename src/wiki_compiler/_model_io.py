"""The one seam every model-backed method goes through, and its failure ledger.

``_call_model`` is the only place this package spawns an agent, so it is the
only place the circuit breaker, the prompt-gate block escalation and the
timeout accounting can live. ``_record_model_failure`` is the breaker's write
side and is called from nowhere else (#11819: a repeated model failure is a
persistent fault, not a transient one, and must name the failing call).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from circuit_breaker import CircuitBreaker
from dedup_store import DedupStore
from prompt_gate_alerts import (
    alert_prompt_gate_block,
    clear_prompt_gate_block,
    is_prompt_gate_blocked,
)

if TYPE_CHECKING:
    from config import Credentials, HydraFlowConfig
    from events import EventBus
    from execution import SubprocessRunner


logger = logging.getLogger("hydraflow.wiki_compiler")


class WikiCompilerModelIOMixin:
    """The one seam every model-backed method goes through, and its failure ledger."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``WikiCompiler.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _bus: EventBus | None
    _config: HydraFlowConfig
    # NOT ``Credentials | None``: the ctor parameter is optional, but ``__init__``
    # substitutes a default ``Credentials()`` before assigning, so the attribute
    # is never None. The seam must state the attribute's type, not the parameter's.
    _credentials: Credentials
    _gate_block_dedup: DedupStore
    _model_breaker: CircuitBreaker
    _runner: SubprocessRunner

    async def _call_model(self, prompt: str, context: str) -> str | None:
        """Call the configured CLI backend for wiki compilation.

        Routes through ``run_lightweight_agent`` so the spawn is
        cost-visible (PromptTelemetry, source="wiki_compilation") and
        pauses on credit exhaustion. ``CreditExhaustedError`` propagates;
        all other errors are logged and swallowed (returns None).
        """
        from runner_utils import run_lightweight_agent  # noqa: PLC0415

        if not self._model_breaker.allow_request():
            # OPEN: skip the spawn entirely rather than burn another full
            # timeout. This is the whole point — an open circuit that still
            # paid for the call would save nothing.
            logger.debug(
                "Wiki compilation skipped — circuit breaker is %s",
                self._model_breaker.state,
            )
            return None

        try:
            result = await run_lightweight_agent(
                runner=self._runner,
                config=self._config,
                tool=self._config.wiki_compilation_tool,
                model=self._config.wiki_compilation_model,
                provider=self._config.wiki_compilation_provider,
                prompt=prompt,
                source="wiki_compilation",
                timeout=self._config.wiki_compilation_timeout,
                gh_token=self._credentials.gh_token,
            )
            if result.returncode != 0:
                if is_prompt_gate_blocked(result.stderr):
                    # A gate block is a persistent policy misconfiguration,
                    # not a transient failure: every tick re-blocks, so a
                    # soft warn would be a PERMANENT silent no-op (#9734
                    # review finding 3). Escalate: ERROR + one SYSTEM_ALERT.
                    await alert_prompt_gate_block(
                        dedup=self._gate_block_dedup,
                        event_bus=self._bus,
                        source="wiki_compilation",
                        repo=self._config.repo or "",
                        detail=result.stderr[:200],
                    )
                    return None
                self._record_model_failure(
                    f"rc={result.returncode}: {result.stderr[:200]}", context
                )
                return None
            self._model_breaker.record_success()
            clear_prompt_gate_block(self._gate_block_dedup, "wiki_compilation")
            return result.stdout if result.stdout else None
        except TimeoutError:
            self._record_model_failure("timed out", context)
            return None
        except (OSError, FileNotFoundError, NotImplementedError) as exc:
            self._record_model_failure(f"unavailable: {exc}", context)
            return None

    def _record_model_failure(self, detail: str, context: str) -> None:
        """Log the failure, and escalate to ERROR when the circuit opens.

        Each individual failure stays a WARNING — one slow call is genuinely
        transient. The ERROR fires exactly once, on the transition to OPEN,
        because that is the moment the failure stops being transient and
        becomes a standing condition an operator should see.
        """
        was_open = self._model_breaker.state == self._model_breaker.OPEN
        self._model_breaker.record_failure()
        if not was_open and self._model_breaker.state == self._model_breaker.OPEN:
            logger.error(
                "Wiki model call %r failing persistently (%s) — circuit "
                "OPEN for %.0fs. The loop will skip its model calls instead of "
                "spending a full timeout per cycle. NOTE: the breaker is shared "
                "by every wiki model operation, so this name is the call that "
                "TRIPPED it, not necessarily the only one affected.",
                context,
                detail,
                self._model_breaker.reset_timeout,
            )
        else:
            logger.warning("Wiki model call %r failed (%s)", context, detail)
