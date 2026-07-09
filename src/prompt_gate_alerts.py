"""Loud, deduplicated escalation for prompt-gate blocks in background loops.

``run_lightweight_agent`` collapses a :class:`prompt_gate.PromptGateBlockedError`
to its soft-failure contract — ``SimpleResult(returncode=-1)`` with the block
reason in ``stderr``. For a caretaker loop a block is a persistent
misconfiguration (repo data class vs ``config.data_class_allowed_backends``):
every tick re-blocks, so treating it like any other rc=-1 soft failure turns
the loop into a PERMANENT silent no-op behind a WARNING log (#9734 review
finding 3).

Callers of ``run_lightweight_agent`` use these helpers on the rc != 0 path
(following the ``cost_budget_alerts`` DedupStore + ``SYSTEM_ALERT`` precedent):

* :func:`is_prompt_gate_blocked` — marker match on ``stderr``
  (:data:`prompt_gate.PROMPT_GATE_BLOCKED_MARKER`).
* :func:`alert_prompt_gate_block` — log at ERROR on every blocked call and
  publish ONE ``SYSTEM_ALERT`` (``kind="prompt_gate_blocked"``) per block
  condition, deduped per source loop via the injected :class:`DedupStore`.
* :func:`clear_prompt_gate_block` — drop the dedup key once a later call
  succeeds, so a NEW block condition re-alerts.

Publish/store failures never raise — a broken alert must not abort the tick.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from events import EventType, HydraFlowEvent
from prompt_gate import PROMPT_GATE_BLOCKED_MARKER

if TYPE_CHECKING:
    from dedup_store import DedupStore
    from events import EventBus

logger = logging.getLogger("hydraflow.prompt_gate_alerts")


def _dedup_key(source: str) -> str:
    return f"prompt_gate_blocked:{source}"


def is_prompt_gate_blocked(stderr: str) -> bool:
    """True when a soft-failure ``stderr`` came from a prompt-gate block."""
    return PROMPT_GATE_BLOCKED_MARKER in stderr


async def alert_prompt_gate_block(
    *,
    dedup: DedupStore,
    event_bus: EventBus | None,
    source: str,
    repo: str,
    detail: str,
) -> None:
    """Escalate a prompt-gate block: ERROR log every call, one SYSTEM_ALERT.

    The ERROR log fires on every blocked tick (the loop genuinely cannot do
    its work); the ``SYSTEM_ALERT`` event is deduped per *source* so the
    dashboard banner fires once per block condition, not every tick. The
    dedup key is cleared by :func:`clear_prompt_gate_block` on the next
    successful call.
    """
    key = _dedup_key(source)
    logger.error(
        "Prompt gate blocked the %s spawn (repo=%s): %s — this loop is a "
        "no-op until the data-class/backend policy is fixed",
        source,
        repo,
        detail,
    )
    try:
        if key in dedup.get():
            return  # already alerted for this block condition
    except Exception:
        logger.warning(
            "DedupStore.get failed in alert_prompt_gate_block", exc_info=True
        )
        return

    if event_bus is not None:
        try:
            await event_bus.publish(
                HydraFlowEvent(
                    type=EventType.SYSTEM_ALERT,
                    data={
                        "kind": "prompt_gate_blocked",
                        "source": source,
                        "repo": repo,
                        "detail": detail,
                        "dedup_key": key,
                    },
                )
            )
        except Exception:
            # Don't mark dedup — retry the publish on the next blocked tick.
            logger.warning("SYSTEM_ALERT publish failed for %s", key, exc_info=True)
            return

    try:
        dedup.add(key)
    except Exception:
        logger.warning("DedupStore.add failed for %s", key, exc_info=True)


def clear_prompt_gate_block(dedup: DedupStore, source: str) -> None:
    """Drop the dedup key after a successful call so a new block re-alerts."""
    key = _dedup_key(source)
    try:
        dedup.discard(key)
    except Exception:
        logger.warning("DedupStore.discard failed for %s", key, exc_info=True)
