"""Module-level constants and helpers shared by the ``orchestrator`` mixins.

Extracted VERBATIM from ``orchestrator.py`` (god-class decomposition, Refs
#11547). ``orchestrator`` imports every mixin module, so a mixin cannot import
``orchestrator`` back — the names both sides need live here instead. Same role
as ``pr_manager_common.py`` and ``review_phase/_common.py`` from #11628. Every
name is re-exported from ``orchestrator`` so the historical
``from orchestrator import _BACKEND_WORKER_LOOPS`` seam keeps working.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

# Same logger as the host — the moved code's records keep their
# pre-extraction ``hydraflow.orchestrator`` origin.
logger = logging.getLogger("hydraflow.orchestrator")


def _log_deferred_task_failure(task: asyncio.Task[Any]) -> None:
    """Log unhandled exceptions from fire-and-forget background tasks (#6513)."""
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is not None:
        logger.warning("Deferred orchestrator task failed", exc_info=exc)


# Delay after a merge to allow GitHub to propagate the merge state.
_POST_MERGE_DELAY: int = 5

# Delay before restarting a loop whose AuthenticationError was refuted by the
# live probe (a transient blip). A restart with no delay would let a loop that
# runs-on-startup re-crash immediately while a sustained blip lasts, spinning
# the supervisor and storming WARNING logs — the same hot-loop pathology #9924
# guarded against on the credit false-positive path. The delay lives inside the
# recreated task, so it never blocks supervision of the other loops (#9621).
_AUTH_TRANSIENT_RESTART_DELAY_S: float = 30.0

# Loops whose primary LLM work routes through a per-role provider dial. Maps
# each loop to the ``HydraFlowConfig`` fields holding its dial and model. This
# includes the four core work loops as well as independently-routed maintenance
# loops; omitting a core loop here mis-scopes provider credit pauses even though
# its runner correctly routes the actual spawn.
# A loop that does MIXED work (dial'd one-shot + some harness spawns, e.g.
# pr_unsticker's HITL analysis) self-heals: while it survives an Anthropic pause
# its harness sub-call re-raises an ``anthropic`` signal that the already-active
# pause absorbs. Keep in sync with the ``*_provider`` dials in config.py.
_BACKEND_WORKER_LOOPS: dict[str, tuple[str, str]] = {
    "triage": ("triage_provider", "triage_model"),
    "plan": ("planner_provider", "planner_model"),
    "implement": ("implementation_provider", "model"),
    "review": ("review_provider", "review_model"),
    "repo_wiki": ("wiki_compilation_provider", "wiki_compilation_model"),
    "adr_reviewer": ("adr_review_provider", "adr_review_model"),
    "pr_unsticker": ("pr_unstick_provider", "background_model"),
    "term_proposer": ("term_proposer_provider", "term_proposer_model"),
    "entry_evidence": ("term_proposer_provider", "term_proposer_model"),
    "intervention_tally": ("maintenance_provider", "intervention_tally_model"),
    "sampled_audit": ("maintenance_provider", "sampled_audit_model"),
    "issue_refinement": ("maintenance_provider", "issue_refinement_model"),
    "skill_prompt_eval": ("maintenance_provider", "skill_prompt_refine_model"),
}

# Core work loops whose runner seams apply repo routing and credit failover.
# Used to distinguish a gateway transport (whose server owns the z.ai key) from
# a direct harness route (which still requires a local z.ai credential).
_PRIMARY_WORK_LOOP_TO_TOOL_FIELD: dict[str, str] = {
    "triage": "triage_tool",
    "plan": "planner_tool",
    "implement": "implementation_tool",
    "review": "review_tool",
}
