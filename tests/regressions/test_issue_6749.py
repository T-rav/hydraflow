"""Regression test for issue #6749.

Three pipeline phases — implement, review, and post-merge — call
``MemoryScorer.record_*`` inside broad ``except Exception`` handlers that
use ``logger.debug`` but never call ``reraise_on_credit_or_bug``.  This
means ``AuthenticationError`` and ``CreditExhaustedError`` are silently
swallowed, masking fatal infrastructure failures as debug noise.

These tests will be RED until each handler calls
``reraise_on_credit_or_bug(exc)`` before logging.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from subprocess_util import AuthenticationError, CreditExhaustedError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scorer_raising(method: str, exc: Exception) -> MagicMock:
    """Return a mock MemoryScorer whose *method* raises *exc*."""
    scorer = MagicMock()
    getattr(scorer, method).side_effect = exc
    return scorer


# ---------------------------------------------------------------------------
# implement_phase — _check_attempt_cap → record_failure_outcome
# ---------------------------------------------------------------------------


class TestImplementPhaseRecordFailurePropagatesFatal:
    """MemoryScorer.record_failure_outcome errors in _check_attempt_cap
    must re-raise AuthenticationError / CreditExhaustedError."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6749 — fix not yet landed", strict=False)
    async def test_auth_error_propagates(self, tmp_path: Path) -> None:
        from tests.conftest import TaskFactory
        from tests.helpers import ConfigFactory, make_implement_phase

        config = ConfigFactory.create(
            max_issue_attempts=2,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        issue = TaskFactory.create()
        phase, _, _ = make_implement_phase(config, [issue])

        # Push past the cap so _check_attempt_cap enters the try block
        phase._state.increment_issue_attempts(42)
        phase._state.increment_issue_attempts(42)

        scorer = _scorer_raising(
            "record_failure_outcome",
            AuthenticationError("bad token"),
        )
        with (
            patch("memory_scoring.MemoryScorer", return_value=scorer),
            pytest.raises(AuthenticationError, match="bad token"),
        ):
            await phase._check_attempt_cap(issue, "agent/issue-42")

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6749 — fix not yet landed", strict=False)
    async def test_credit_error_propagates(self, tmp_path: Path) -> None:
        from tests.conftest import TaskFactory
        from tests.helpers import ConfigFactory, make_implement_phase

        config = ConfigFactory.create(
            max_issue_attempts=2,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        issue = TaskFactory.create()
        phase, _, _ = make_implement_phase(config, [issue])

        phase._state.increment_issue_attempts(42)
        phase._state.increment_issue_attempts(42)

        scorer = _scorer_raising(
            "record_failure_outcome",
            CreditExhaustedError("quota exceeded"),
        )
        with (
            patch("memory_scoring.MemoryScorer", return_value=scorer),
            pytest.raises(CreditExhaustedError, match="quota exceeded"),
        ):
            await phase._check_attempt_cap(issue, "agent/issue-42")


# ---------------------------------------------------------------------------
# review_phase — _escalate_to_hitl → record_hitl_outcome
# ---------------------------------------------------------------------------


class TestReviewPhaseRecordHitlPropagatesFatal:
    """MemoryScorer.record_hitl_outcome errors in _escalate_to_hitl
    must re-raise AuthenticationError / CreditExhaustedError."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6749 — fix not yet landed", strict=False)
    async def test_auth_error_propagates(self, tmp_path: Path) -> None:
        from models import HitlEscalation
        from tests.helpers import ConfigFactory, make_review_phase

        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        phase = make_review_phase(config)

        esc = HitlEscalation(
            issue_number=42,
            pr_number=None,
            cause="test cause",
            origin_label="hydraflow-review",
            comment="Test escalation",
            post_on_pr=False,
        )

        scorer = _scorer_raising(
            "record_hitl_outcome",
            AuthenticationError("expired credentials"),
        )
        with (
            patch("memory_scoring.MemoryScorer", return_value=scorer),
            pytest.raises(AuthenticationError, match="expired credentials"),
        ):
            await phase._escalate_to_hitl(esc)

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6749 — fix not yet landed", strict=False)
    async def test_credit_error_propagates(self, tmp_path: Path) -> None:
        from models import HitlEscalation
        from tests.helpers import ConfigFactory, make_review_phase

        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        phase = make_review_phase(config)

        esc = HitlEscalation(
            issue_number=42,
            pr_number=None,
            cause="test cause",
            origin_label="hydraflow-review",
            comment="Test escalation",
            post_on_pr=False,
        )

        scorer = _scorer_raising(
            "record_hitl_outcome",
            CreditExhaustedError("out of credits"),
        )
        with (
            patch("memory_scoring.MemoryScorer", return_value=scorer),
            pytest.raises(CreditExhaustedError, match="out of credits"),
        ):
            await phase._escalate_to_hitl(esc)


# ---------------------------------------------------------------------------
# post_merge_handler — handle_approved → record_merge_outcome
# ---------------------------------------------------------------------------


class TestPostMergeRecordMergePropagatesFatal:
    """MemoryScorer.record_merge_outcome errors in handle_approved
    must re-raise AuthenticationError / CreditExhaustedError."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6749 — fix not yet landed", strict=False)
    async def test_auth_error_propagates(self, tmp_path: Path) -> None:
        from unittest.mock import AsyncMock

        from events import EventBus
        from models import MergeApprovalContext, PRInfo, ReviewResult
        from post_merge_handler import PostMergeHandler
        from state import StateTracker
        from tests.conftest import TaskFactory

        config_factory = __import__(
            "tests.helpers", fromlist=["ConfigFactory"]
        ).ConfigFactory
        config = config_factory.create(
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        mock_prs.merge_pr = AsyncMock(return_value=True)
        mock_prs.expected_pr_title = MagicMock(return_value="Fixes #42: test")
        mock_prs.update_pr_title = AsyncMock()

        handler = PostMergeHandler(
            config=config,
            state=state,
            prs=mock_prs,
            event_bus=EventBus(),
            ac_generator=None,
            retrospective=None,
            verification_judge=None,
            epic_checker=None,
        )

        issue = TaskFactory.create()
        pr = PRInfo(number=100, issue_number=42, branch="agent/issue-42")
        result = ReviewResult(pr_number=100, issue_number=42)

        scorer = _scorer_raising(
            "record_merge_outcome",
            AuthenticationError("invalid token"),
        )

        ctx = MergeApprovalContext(
            pr=pr,
            issue=issue,
            result=result,
            diff="some diff",
            worker_id=0,
            ci_gate_fn=AsyncMock(),
            escalate_fn=AsyncMock(),
            publish_fn=AsyncMock(),
        )

        with (
            patch("memory_scoring.MemoryScorer", return_value=scorer),
            pytest.raises(AuthenticationError, match="invalid token"),
        ):
            await handler.handle_approved(ctx)

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6749 — fix not yet landed", strict=False)
    async def test_credit_error_propagates(self, tmp_path: Path) -> None:
        from unittest.mock import AsyncMock

        from events import EventBus
        from models import MergeApprovalContext, PRInfo, ReviewResult
        from post_merge_handler import PostMergeHandler
        from state import StateTracker
        from tests.conftest import TaskFactory

        config_factory = __import__(
            "tests.helpers", fromlist=["ConfigFactory"]
        ).ConfigFactory
        config = config_factory.create(
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        mock_prs.merge_pr = AsyncMock(return_value=True)
        mock_prs.expected_pr_title = MagicMock(return_value="Fixes #42: test")
        mock_prs.update_pr_title = AsyncMock()

        handler = PostMergeHandler(
            config=config,
            state=state,
            prs=mock_prs,
            event_bus=EventBus(),
            ac_generator=None,
            retrospective=None,
            verification_judge=None,
            epic_checker=None,
        )

        issue = TaskFactory.create()
        pr = PRInfo(number=100, issue_number=42, branch="agent/issue-42")
        result = ReviewResult(pr_number=100, issue_number=42)

        scorer = _scorer_raising(
            "record_merge_outcome",
            CreditExhaustedError("billing limit hit"),
        )

        ctx = MergeApprovalContext(
            pr=pr,
            issue=issue,
            result=result,
            diff="some diff",
            worker_id=0,
            ci_gate_fn=AsyncMock(),
            escalate_fn=AsyncMock(),
            publish_fn=AsyncMock(),
        )

        with (
            patch("memory_scoring.MemoryScorer", return_value=scorer),
            pytest.raises(CreditExhaustedError, match="billing limit hit"),
        ):
            await handler.handle_approved(ctx)
