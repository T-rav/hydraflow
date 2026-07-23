"""Regression: diagnostic escalation must not re-arm hitl labels when a
resolving PR is already open (#10262).

``DiagnosticLoop._escalate_to_hitl`` always swapped to ``hydraflow-hitl`` and
re-added ``hitl-escalation`` + ``diagnose-failed`` — even on the comment-dedup
hit path (the log says "labels still applied"). If an issue is re-routed into
diagnose while a *prior* attempt's resolving PR is already open, reconciliation
(the Auto-Agent routes a resolved ``diagnose-failed`` issue back to review and
clears those labels) has just cleared the escalation labels. Re-arming them
here flaps the labels and renews auto-agent dispatch pressure.

The fix consults the same resolving-PR signal the reconciler uses
(``find_open_pr_for_branch`` on the ``agent/issue-{N}`` branch convention) and
skips the escalation-label re-arm when an open resolving PR exists — while
preserving today's escalate behaviour when there is no open PR.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from diagnostic_loop import DiagnosticLoop
from models import PRInfo
from tests.helpers import make_bg_loop_deps

_ESCALATION_LABELS = ["hitl-escalation", "diagnose-failed"]


def _make_loop(tmp_path: Path) -> tuple[DiagnosticLoop, MagicMock]:
    """Build a DiagnosticLoop with an all-async-mocked PRPort.

    Returns (loop, prs_mock).
    """
    deps = make_bg_loop_deps(tmp_path)
    object.__setattr__(deps.config, "diagnostic_loop_enabled", True)

    prs = MagicMock()
    prs.post_comment = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()
    prs.add_labels = AsyncMock()
    # Default: no open resolving PR.
    prs.find_open_pr_for_branch = AsyncMock(return_value=None)

    loop = DiagnosticLoop(
        config=deps.config,
        runner=MagicMock(),
        prs=prs,
        state=MagicMock(),
        deps=deps.loop_deps,
    )
    return loop, prs


def _added_escalation_labels(prs: MagicMock) -> bool:
    """Whether ``add_labels`` was awaited with the escalation label set."""
    return any(
        call.args[1] == _ESCALATION_LABELS
        for call in prs.add_labels.await_args_list
    )


@pytest.mark.asyncio
async def test_no_open_pr_still_escalates(tmp_path: Path) -> None:
    """Without an open resolving PR, escalation labels are still applied."""
    loop, prs = _make_loop(tmp_path)
    prs.find_open_pr_for_branch.return_value = None

    await loop._escalate_to_hitl(42, comment="Diagnosis prose")

    prs.add_labels.assert_awaited_once_with(42, _ESCALATION_LABELS)


@pytest.mark.asyncio
async def test_open_resolving_pr_skips_label_rearm(tmp_path: Path) -> None:
    """With an open resolving PR, the escalation labels are NOT re-applied."""
    loop, prs = _make_loop(tmp_path)
    prs.find_open_pr_for_branch.return_value = PRInfo(
        number=123, issue_number=42, branch="agent/issue-42"
    )

    await loop._escalate_to_hitl(42, comment="Diagnosis prose")

    assert not _added_escalation_labels(prs)
    prs.find_open_pr_for_branch.assert_awaited_once()


@pytest.mark.asyncio
async def test_open_resolving_pr_skips_rearm_on_dedup_hit_path(
    tmp_path: Path,
) -> None:
    """The dedup-hit path ("labels still applied") also skips the re-arm.

    Pre-seed the comment-dedup store so the diagnosis comment is treated as
    already posted — the historical bug re-armed the labels anyway.
    """
    loop, prs = _make_loop(tmp_path)
    comment = "Diagnosis prose"
    digest = hashlib.sha256(comment.encode("utf-8")).hexdigest()[:16]
    loop._hitl_comment_dedup.set_all({f"42:{digest}"})
    prs.find_open_pr_for_branch.return_value = PRInfo(
        number=123, issue_number=42, branch="agent/issue-42"
    )

    await loop._escalate_to_hitl(42, comment=comment)

    # Dedup hit → comment skipped, and the open PR → no label re-arm.
    prs.post_comment.assert_not_awaited()
    assert not _added_escalation_labels(prs)


@pytest.mark.asyncio
async def test_absence_sentinel_pr_zero_still_escalates(tmp_path: Path) -> None:
    """A ``PRInfo(number=0)`` absence sentinel is treated as no open PR."""
    loop, prs = _make_loop(tmp_path)
    prs.find_open_pr_for_branch.return_value = PRInfo(
        number=0, issue_number=42, branch="agent/issue-42"
    )

    await loop._escalate_to_hitl(42, comment="Diagnosis prose")

    prs.add_labels.assert_awaited_once_with(42, _ESCALATION_LABELS)
