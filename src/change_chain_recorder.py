"""Anchors a change's artifact chain on the CH-1 stream (ADR-0149).

Called once per planned issue, from the plan phase, at the only moment
where all three plan-time artifacts exist at once: after the criteria
stage has drafted and judged, with the issue body and plan text in hand.

Deliberately NOT in ``planner._save_plan``. The planner writes its plan
before the criteria stage runs, so a recorder wired there could only ever
anchor two of the three artifacts and would have to stash the third on the
instance to catch up. The seam that has the whole chain is the caller's.

The append is best-effort in the same sense the planner's disk write is: a
planning run must not die because an audit stream is unwritable. But it is
logged at warning rather than swallowed, because a change with no anchor is
a change whose committed chain can never be verified — the gate has nothing
to compare against, and an unverifiable chain that looks verified is worse
than an absent one.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from audit_chain import AuditChain
from change_chain import (
    ChainArtifact,
    ChainRecord,
    digest,
    render_criteria,
    render_intent,
    render_plan,
)

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from models import Task
    from plan_phase_adversarial import CriteriaDraft

logger = logging.getLogger(__name__)


def build_record(
    issue: Task,
    plan_text: str,
    summary: str,
    draft: CriteriaDraft | None,
    *,
    recorded_at: str,
) -> ChainRecord:
    """Render a change's plan-time artifacts and digest them.

    Pure: no clock read, no filesystem, no network. *recorded_at* is passed
    in so the caller owns the only non-deterministic input and the record is
    reproducible in a test.
    """
    rendered: dict[ChainArtifact, str] = {
        ChainArtifact.INTENT: render_intent(
            issue.id, issue.title, issue.body or "", recorded_at
        ),
        ChainArtifact.PLAN: render_plan(issue.id, plan_text, summary),
    }
    if draft is not None:
        rendered[ChainArtifact.CRITERIA] = render_criteria(
            issue.id,
            draft.criteria,
            draft.judge_verdict,
            draft.forwarded_concerns,
        )
    return ChainRecord(
        issue_number=issue.id,
        digests={artifact: digest(body) for artifact, body in rendered.items()},
        rendered=rendered,
        recorded_at=recorded_at,
    )


def record_chain(
    config: HydraFlowConfig,
    issue: Task,
    plan_text: str,
    summary: str,
    draft: CriteriaDraft | None,
) -> ChainRecord | None:
    """Append *issue*'s plan-time chain to CH-1. Returns the record, or None.

    ``None`` means nothing was anchored — the kill-switch is off, or the
    stream could not be written.
    """
    if not config.change_chain_enabled:
        return None
    record = build_record(
        issue,
        plan_text,
        summary,
        draft,
        recorded_at=datetime.now(UTC).isoformat(),
    )
    try:
        config.change_chain_path.parent.mkdir(parents=True, exist_ok=True)
        AuditChain(config.change_chain_path).append(record.to_json_dict())
    except OSError:
        logger.warning(
            "Could not anchor the artifact chain for issue #%d — its "
            "committed chain will not be verifiable",
            issue.id,
            exc_info=True,
            extra={"issue": issue.id},
        )
        return None
    logger.info(
        "Anchored %d chain artifacts for issue #%d",
        len(record.digests),
        issue.id,
        extra={"issue": issue.id},
    )
    return record
