"""Regression guard for #10413 — self-review on the bot's own PR is graceful.

``PRManager.submit_review`` intends to swallow the "you can't review your own
pull request" error from GitHub (raise ``SelfReviewError`` so the caller falls
back — the merge still proceeds on green; staging requires 0 approvals). The
approve branch matched ``"cannot approve your own pull request"`` (one word),
but the live GraphQL error is ``"Review Can not approve your own pull request"``
(``"can not"``, two words), so the approve case fell through to a scary
``WARNING`` + ``return False`` on *every* bot-PR merge (#10407, #10409, …).

Fix: match the STABLE core phrase (``"approve your own pull request"`` /
``"request changes on your own pull request"``), robust to the cannot/can-not
spacing. A genuinely-different review failure must still return ``False``.
"""

from __future__ import annotations

import pytest

from comment_formatter import SelfReviewError
from models import ReviewVerdict
from tests.helpers import make_pr_manager

# The real messages GitHub surfaces (two-word "Can not"), as they appear inside
# the RuntimeError raised by _run_with_body_file.
_APPROVE_ERR = (
    "failed to create review: GraphQL: Review Can not approve your own "
    "pull request (addPullRequestReview)"
)
_REQUEST_CHANGES_ERR = (
    "failed to create review: GraphQL: Review Can not request changes on your "
    "own pull request (addPullRequestReview)"
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verdict", "message"),
    [
        (ReviewVerdict.APPROVE, _APPROVE_ERR),
        (ReviewVerdict.REQUEST_CHANGES, _REQUEST_CHANGES_ERR),
    ],
)
async def test_self_review_raises_selfreviewerror_not_warning(
    config, event_bus, verdict, message
) -> None:
    """A self-review rejection is recognized and raised as SelfReviewError."""
    mgr = make_pr_manager(config, event_bus)

    async def _raise(*_args, **_kwargs):
        raise RuntimeError(message)

    mgr._run_with_body_file = _raise  # type: ignore[method-assign]

    with pytest.raises(SelfReviewError):
        await mgr.submit_review(101, verdict, "body")


@pytest.mark.asyncio
async def test_genuine_review_failure_still_returns_false(config, event_bus) -> None:
    """A non-self-review failure must NOT be swallowed as SelfReviewError."""
    mgr = make_pr_manager(config, event_bus)

    async def _raise(*_args, **_kwargs):
        raise RuntimeError("failed to create review: GraphQL: Something else broke")

    mgr._run_with_body_file = _raise  # type: ignore[method-assign]

    result = await mgr.submit_review(101, ReviewVerdict.APPROVE, "body")
    assert result is False
