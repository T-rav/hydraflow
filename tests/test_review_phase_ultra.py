"""Integration tests for the ultra tier's verdict-fold in ReviewPhase (#10555).

These exercise ``ReviewPhase._maybe_fold_ultra_review`` and
``_fold_ultra_findings`` directly. They construct a bare ``ReviewPhase`` via
``__new__`` and inject only the collaborators those methods touch
(``_config``, ``_prs``, ``_ultra_runner``) — no subprocess, no real
reviewer, per the plan's "patch ReviewPhase._ultra_runner" strategy.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import ultra_review as ur
from config import HydraFlowConfig
from models import PRInfo, ReviewResult, ReviewVerdict
from review_phase import ReviewPhase
from subprocess_util import CreditExhaustedError


def _pr(number: int = 100, issue_number: int = 55) -> PRInfo:
    return PRInfo(number=number, issue_number=issue_number, branch="agent/issue-55")


def _approve_result() -> ReviewResult:
    return ReviewResult(
        pr_number=100,
        issue_number=55,
        verdict=ReviewVerdict.APPROVE,
        summary="Looks good.",
    )


class _FakeUltraRunner:
    """Stand-in for ReviewPhase._ultra_runner returning a scripted result."""

    def __init__(self, result: ur.UltraReviewResult) -> None:
        self._result = result
        self.calls = 0

    async def run(self, *, prompt: str, issue_number: int) -> ur.UltraReviewResult:
        self.calls += 1
        return self._result


def _phase(
    *,
    config: HydraFlowConfig,
    labels: list[str],
    runner: object | None = None,
) -> tuple[ReviewPhase, AsyncMock]:
    phase = ReviewPhase.__new__(ReviewPhase)
    phase._config = config
    prs = AsyncMock()
    # Label reads and PR comments both go through PRPort (self._prs).
    prs.get_issue_labels = AsyncMock(return_value=labels)
    phase._prs = prs
    if runner is not None:
        phase._ultra_runner = runner  # type: ignore[assignment]
    return phase, prs


@pytest.mark.asyncio
async def test_disabled_dial_spawns_nothing_and_keeps_verdict() -> None:
    config = HydraFlowConfig(review_ultra_enabled=False)
    runner = _FakeUltraRunner(ur.UltraReviewResult())
    phase, prs = _phase(config=config, labels=[ur.ULTRA_REVIEW_LABEL], runner=runner)

    result = await phase._maybe_fold_ultra_review(_pr(), _approve_result(), "diff")

    assert result.verdict == ReviewVerdict.APPROVE
    assert runner.calls == 0
    # Default-off must issue zero ultra work — not even a label read.
    phase._prs.get_issue_labels.assert_not_awaited()
    prs.post_pr_comment.assert_not_awaited()


@pytest.mark.asyncio
async def test_enabled_but_not_gated_keeps_verdict() -> None:
    config = HydraFlowConfig(review_ultra_enabled=True)
    runner = _FakeUltraRunner(ur.UltraReviewResult())
    # No review:ultra label and auto-high-blast off -> gate closed.
    phase, prs = _phase(config=config, labels=["ready"], runner=runner)

    result = await phase._maybe_fold_ultra_review(_pr(), _approve_result(), "diff")

    assert result.verdict == ReviewVerdict.APPROVE
    assert runner.calls == 0
    phase._prs.get_issue_labels.assert_awaited_once()


@pytest.mark.asyncio
async def test_material_findings_flip_approve_to_request_changes() -> None:
    config = HydraFlowConfig(review_ultra_enabled=True)
    ultra = ur.UltraReviewResult(
        findings=[ur.UltraFinding(description="real defect", confidence=95)]
    )
    runner = _FakeUltraRunner(ultra)
    phase, prs = _phase(config=config, labels=[ur.ULTRA_REVIEW_LABEL], runner=runner)

    result = await phase._maybe_fold_ultra_review(_pr(), _approve_result(), "diff")

    assert result.verdict == ReviewVerdict.REQUEST_CHANGES
    assert runner.calls == 1
    # Findings surface in the summary text; no advisory comment when blocking.
    assert "real defect" in result.summary
    assert "Ultra deep-review findings" in result.summary
    prs.post_pr_comment.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_material_findings_keeps_verdict_untouched() -> None:
    config = HydraFlowConfig(review_ultra_enabled=True)
    runner = _FakeUltraRunner(ur.UltraReviewResult(findings=[]))
    phase, prs = _phase(config=config, labels=[ur.ULTRA_REVIEW_LABEL], runner=runner)

    result = await phase._maybe_fold_ultra_review(_pr(), _approve_result(), "diff")

    assert result.verdict == ReviewVerdict.APPROVE
    prs.post_pr_comment.assert_not_awaited()


@pytest.mark.asyncio
async def test_subthreshold_findings_posted_as_comment_not_blocking() -> None:
    config = HydraFlowConfig(review_ultra_enabled=True)
    ultra = ur.UltraReviewResult(
        findings=[ur.UltraFinding(description="minor nit", confidence=50)]
    )
    runner = _FakeUltraRunner(ultra)
    phase, prs = _phase(config=config, labels=[ur.ULTRA_REVIEW_LABEL], runner=runner)

    result = await phase._maybe_fold_ultra_review(_pr(), _approve_result(), "diff")

    assert result.verdict == ReviewVerdict.APPROVE
    prs.post_pr_comment.assert_awaited_once()
    (_pr_num, comment) = prs.post_pr_comment.await_args.args
    assert "minor nit" in comment


@pytest.mark.asyncio
async def test_degraded_run_leaves_verdict_intact() -> None:
    config = HydraFlowConfig(review_ultra_enabled=True)
    runner = _FakeUltraRunner(ur.UltraReviewResult(degraded=True))
    phase, prs = _phase(config=config, labels=[ur.ULTRA_REVIEW_LABEL], runner=runner)

    result = await phase._maybe_fold_ultra_review(_pr(), _approve_result(), "diff")

    assert result.verdict == ReviewVerdict.APPROVE
    prs.post_pr_comment.assert_not_awaited()


@pytest.mark.asyncio
async def test_credit_exhaustion_from_runner_propagates() -> None:
    config = HydraFlowConfig(review_ultra_enabled=True)

    class _CreditRunner:
        async def run(self, *, prompt: str, issue_number: int):  # noqa: ANN201
            raise CreditExhaustedError("usage limit reached")

    phase, _prs = _phase(
        config=config, labels=[ur.ULTRA_REVIEW_LABEL], runner=_CreditRunner()
    )

    with pytest.raises(CreditExhaustedError):
        await phase._maybe_fold_ultra_review(_pr(), _approve_result(), "diff")


@pytest.mark.asyncio
async def test_label_read_failure_skips_tier_soft() -> None:
    config = HydraFlowConfig(review_ultra_enabled=True)
    runner = _FakeUltraRunner(
        ur.UltraReviewResult(findings=[ur.UltraFinding(description="x", confidence=99)])
    )
    phase, _prs = _phase(config=config, labels=[], runner=runner)
    phase._prs.get_issue_labels = AsyncMock(side_effect=RuntimeError("gh down"))

    result = await phase._maybe_fold_ultra_review(_pr(), _approve_result(), "diff")

    # Unreadable labels must not crash the review nor fire the tier.
    assert result.verdict == ReviewVerdict.APPROVE
    assert runner.calls == 0
