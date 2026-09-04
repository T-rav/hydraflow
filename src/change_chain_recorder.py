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

import json
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
        _write_bodies(config, record)
        config.change_chain_path.parent.mkdir(parents=True, exist_ok=True)
        AuditChain(config.change_chain_path).append(record.to_json_dict())
    except (OSError, ValueError):
        # ValueError as well as OSError: `AuditChain.append` scrubs the
        # serialized payload with regexes whose value classes have been
        # observed to corrupt it into invalid JSON, raising JSONDecodeError
        # (a ValueError). This module keeps arbitrary prose out of the
        # payload precisely so that cannot happen here — but a planning run
        # must not die on an audit-stream defect either way, and the guard
        # costs nothing.
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


def _write_bodies(config: HydraFlowConfig, record: ChainRecord) -> None:
    """Write the rendered bodies to the local chain cache.

    Separate from the CH-1 append because the two carry different things: the
    stream anchors digests and must stay small, scrub-safe and permanent; the
    cache holds bytes for the worktree that will materialise them, and is
    ordinary disposable disk state. The writer digest-checks the cache against
    the anchor before committing anything, so a mutated cache is caught rather
    than trusted.

    Always UTF-8: ``digest`` hashes UTF-8 bytes, so a locale-encoded write
    would hash one thing and store another.
    """
    directory = config.chain_bodies_dir / f"issue-{record.issue_number}"
    directory.mkdir(parents=True, exist_ok=True)
    for artifact, body in record.rendered.items():
        (directory / f"{artifact.value}.md").write_text(body, encoding="utf-8")


def latest_record(config: HydraFlowConfig, issue_number: int) -> ChainRecord | None:
    """The newest anchored record for *issue_number*, or None.

    Shared by the writer (which materialises the bodies it names) and the
    gate (which verifies the committed files against it), so the two cannot
    disagree about which record is current.

    Scanned from the END: newest wins, so the first match walking backwards
    is the answer. A re-planned issue appends a second record, and both
    readers must see the plan the implementer was actually given.
    """
    path = config.change_chain_path
    if not path.exists():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        logger.warning(
            "Could not read the chain stream for issue #%d",
            issue_number,
            exc_info=True,
            extra={"issue": issue_number},
        )
        return None
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get("issue_number") == issue_number:
            return ChainRecord.from_json_dict(payload)
    return None
