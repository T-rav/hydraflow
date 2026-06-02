"""Regression test for issue #6735.

``EpicSweeperLoop._do_work()`` wraps each epic's sweep attempt in
``except Exception: logger.exception(...)`` and continues.  This catches
``AuthenticationError`` and ``CreditExhaustedError`` (both subclass
``RuntimeError``) as if they were per-epic errors, then continues to the
next item.  Auth failures and credit exhaustion should propagate to the
background loop supervisor so the orchestrator can pause or stop, not be
silently swallowed.

These tests will be RED until the handler re-raises
``AuthenticationError`` and ``CreditExhaustedError`` before the generic
``except Exception`` block (e.g. via ``reraise_on_credit_or_bug``).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from epic_sweeper_loop import EpicSweeperLoop
from subprocess_util import AuthenticationError, CreditExhaustedError
from tests.conftest import IssueFactory
from tests.helpers import make_bg_loop_deps

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_issue(
    number: int, *, state: str = "open", body: str = "", labels: list[str] | None = None
):
    """Create a mock GitHubIssue."""
    return IssueFactory.create(
        number=number,
        title=f"Issue #{number}",
        body=body,
        labels=labels or [],
        state=state,
    )


def _make_epic(number: int, body: str):
    """Create a mock epic issue with sub-issue refs in body."""
    return _make_issue(number, body=body, labels=["hydraflow-epic"])


def _make_loop(tmp_path: Path):
    """Build an EpicSweeperLoop with mock dependencies."""
    deps = make_bg_loop_deps(tmp_path, enabled=True, epic_sweep_interval=3600)

    fetcher = MagicMock()
    fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])
    fetcher.fetch_issue_by_number = AsyncMock(return_value=None)

    prs = MagicMock()
    prs.update_issue_body = AsyncMock()
    prs.add_labels = AsyncMock()
    prs.post_comment = AsyncMock()
    prs.close_issue = AsyncMock()

    state = MagicMock()
    state.get_epic_state = MagicMock(return_value=None)

    loop = EpicSweeperLoop(
        config=deps.config,
        fetcher=fetcher,
        prs=prs,
        state=state,
        deps=deps.loop_deps,
    )
    return loop, fetcher, prs, state


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEpicSweeperPropagatesFatalErrors:
    """AuthenticationError and CreditExhaustedError must propagate out of
    ``_do_work``, not be caught by the per-epic handler."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6735 — fix not yet landed", strict=False)
    async def test_authentication_error_propagates(self, tmp_path: Path) -> None:
        """AuthenticationError must NOT be caught by except Exception."""
        loop, fetcher, _prs, _state = _make_loop(tmp_path)
        epic = _make_epic(100, "- [ ] #10\n- [ ] #20")
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[epic])
        fetcher.fetch_issue_by_number = AsyncMock(
            side_effect=AuthenticationError("bad credentials"),
        )

        with pytest.raises(AuthenticationError, match="bad credentials"):
            await loop._do_work()

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6735 — fix not yet landed", strict=False)
    async def test_credit_exhausted_error_propagates(self, tmp_path: Path) -> None:
        """CreditExhaustedError must NOT be caught by except Exception."""
        loop, fetcher, _prs, _state = _make_loop(tmp_path)
        epic = _make_epic(100, "- [ ] #10\n- [ ] #20")
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[epic])
        fetcher.fetch_issue_by_number = AsyncMock(
            side_effect=CreditExhaustedError("usage limit reached"),
        )

        with pytest.raises(CreditExhaustedError, match="usage limit reached"):
            await loop._do_work()

    @pytest.mark.asyncio
    async def test_plain_runtime_error_still_caught(self, tmp_path: Path) -> None:
        """Plain RuntimeError should still be caught — loop continues."""
        loop, fetcher, _prs, _state = _make_loop(tmp_path)
        epic1 = _make_epic(100, "- [ ] #10")
        epic2 = _make_epic(200, "- [ ] #20")
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[epic1, epic2])

        async def side_effect(n: int):
            if n == 10:
                raise RuntimeError("transient network error")
            return _make_issue(n, state="closed")

        fetcher.fetch_issue_by_number = AsyncMock(side_effect=side_effect)

        # This should NOT raise — the generic handler catches plain RuntimeError.
        result = await loop._do_work()
        assert result is not None
        assert result["swept"] == 1  # epic2 still swept despite epic1 error
