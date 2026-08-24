"""What the unsticker learns from a fix it just made.

Persisting a troubleshooting pattern and asking the agent to reflect on
the fix are knowledge capture, not repair: they run AFTER the outcome is
known, they are best-effort, and a failure here must never change whether
the PR got unstuck.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from exception_classify import reraise_on_credit_or_bug
from prompt_gate_alerts import (
    alert_prompt_gate_block,
    clear_prompt_gate_block,
    is_prompt_gate_blocked,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from agent import AgentRunner
    from config import Credentials, HydraFlowConfig
    from dedup_store import DedupStore
    from events import EventBus
    from troubleshooting_store import (
        TroubleshootingPattern,
        TroubleshootingPatternStore,
    )


logger = logging.getLogger("hydraflow.pr_unsticker")


class PRUnstickerReflectionMixin:
    """What the unsticker learns from a fix it just made."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``PRUnsticker.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _agents: AgentRunner
    _bus: EventBus
    _config: HydraFlowConfig
    _credentials: Credentials
    _gate_block_dedup: DedupStore
    _troubleshooting_store: TroubleshootingPatternStore | None

    async def _persist_troubleshooting_pattern(
        self,
        transcript: str,
        issue_number: int,
        language: str,
        *,
        issue_labels: Sequence[str] = (),
    ) -> None:
        """Extract and persist a troubleshooting pattern from a successful fix.

        Two-stage approach:
        1. Check for an explicit ``TROUBLESHOOTING_PATTERN`` block (free, instant).
        2. If none found, run a cheap model reflection to extract the insight
           and check novelty against the existing store.

        *issue_labels* carries the fixed issue's labels into the reflection
        spawn's CH-6 gate (upward-only ``data-class:`` elevation).
        """
        if self._troubleshooting_store is None:
            return
        try:
            from troubleshooting_store import extract_troubleshooting_pattern

            # Stage 1: explicit block from agent
            pattern = extract_troubleshooting_pattern(
                transcript, issue_number, language
            )
            if pattern is not None:
                self._troubleshooting_store.append_pattern(pattern)
                logger.info(
                    "Persisted troubleshooting pattern '%s' from issue #%d (explicit)",
                    pattern.pattern_name,
                    issue_number,
                )
                return

            # Stage 2: self-reflection via cheap model
            pattern = await self._reflect_on_fix(
                transcript, issue_number, language, issue_labels=issue_labels
            )
            if pattern is not None:
                self._troubleshooting_store.append_pattern(pattern)
                logger.info(
                    "Persisted troubleshooting pattern '%s' from issue #%d (reflection)",
                    pattern.pattern_name,
                    issue_number,
                )
        except (RuntimeError, OSError, ImportError) as exc:
            # CreditExhaustedError (raised by _reflect_on_fix when the cheap
            # reflection model signals credit-out) subclasses RuntimeError —
            # reraise it (plus auth/likely-bug) so the billing signal is not
            # buried under "failed to persist troubleshooting pattern".
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "Failed to persist troubleshooting pattern for issue #%d: %s",
                issue_number,
                exc,
                exc_info=True,
            )

    async def _reflect_on_fix(
        self,
        transcript: str,
        issue_number: int,
        language: str,
        *,
        issue_labels: Sequence[str] = (),
    ) -> TroubleshootingPattern | None:
        """Run a cheap model to extract a troubleshooting pattern from the transcript.

        Compares against known patterns in the store and only returns a pattern
        if it identifies something novel.  Returns ``None`` if the model call
        fails or nothing new is found.
        """
        from troubleshooting_store import extract_troubleshooting_pattern

        store = self._troubleshooting_store
        if store is None:
            return None

        known = store.load_patterns(limit=50)
        known_block = "\n".join(f"- {p.pattern_name}: {p.description}" for p in known)

        # Truncate transcript to keep the prompt small
        max_transcript = 6000
        trimmed = (
            transcript[-max_transcript:]
            if len(transcript) > max_transcript
            else transcript
        )

        prompt = f"""You are analyzing a successful CI timeout fix to extract reusable troubleshooting knowledge.

## Transcript (tail)

{trimmed}

## Already-known patterns

{known_block or "(none)"}

## Task

If the fix above addresses a hang pattern that is NOT already covered by the known patterns,
emit a structured block. If the fix is just a variant of an existing pattern, output NOTHING.

Only emit a block if the root cause is genuinely distinct from every known pattern above.

```
TROUBLESHOOTING_PATTERN_START
pattern_name: <short_snake_case_key>
description: <what causes the hang — one sentence>
fix_strategy: <how to fix it — one sentence>
TROUBLESHOOTING_PATTERN_END
```

If nothing novel, output exactly: NO_NEW_PATTERN"""

        from runner_utils import run_lightweight_agent  # noqa: PLC0415

        tool = self._config.background_tool
        if tool == "inherit":
            tool = "claude"
        model = self._config.background_model or "haiku"

        try:
            # run_lightweight_agent builds the command, raises
            # CreditExhaustedError on credit-out (exception OR stdout/stderr
            # text) so the outer loop pauses on the billing signal, reraises
            # likely-bugs, collapses transient failures to rc=-1, and records
            # PromptTelemetry(source="pr_unsticker").
            result = await run_lightweight_agent(
                runner=self._agents._runner,
                config=self._config,
                tool=tool,
                model=model,
                provider=self._config.pr_unstick_provider,
                prompt=prompt,
                source="pr_unsticker",
                timeout=60.0,
                gh_token=self._credentials.gh_token,
                issue_number=issue_number,
                issue_labels=issue_labels,
            )
            if result.returncode != 0:
                if is_prompt_gate_blocked(result.stderr):
                    # A gate block is a persistent policy misconfiguration,
                    # not a transient failure: every reflection re-blocks, so
                    # a debug log would be a PERMANENT silent no-op (#9734
                    # review finding 3). Escalate: ERROR + one SYSTEM_ALERT.
                    await alert_prompt_gate_block(
                        dedup=self._gate_block_dedup,
                        event_bus=self._bus,
                        source="pr_unsticker",
                        repo=self._config.repo or "",
                        detail=result.stderr[:200],
                    )
                    return None
                logger.debug(
                    "Troubleshooting reflection model failed (rc=%d)",
                    result.returncode,
                )
                return None
            clear_prompt_gate_block(self._gate_block_dedup, "pr_unsticker")

            output = result.stdout or ""
            if "NO_NEW_PATTERN" in output:
                logger.debug(
                    "Reflection found no novel pattern for issue #%d", issue_number
                )
                return None

            return extract_troubleshooting_pattern(output, issue_number, language)
        except (TimeoutError, OSError, FileNotFoundError) as exc:
            logger.debug("Troubleshooting reflection unavailable: %s", exc)
            return None
