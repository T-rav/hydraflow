"""Regression test for issue #6751.

Bug: ``CrateManager.auto_package_if_needed`` catches ``RuntimeError`` in the
milestone-assignment loop (line ~157).  Because both ``CreditExhaustedError``
and ``AuthenticationError`` are ``RuntimeError`` subclasses, they are silently
swallowed — the loop logs a warning and continues, orphaning remaining issues
from the crate with no signal to the caller.

Expected behaviour after fix:
  - ``CreditExhaustedError`` during milestone assignment propagates instead of
    being silently caught.
  - ``AuthenticationError`` during milestone assignment propagates instead of
    being silently caught.
  - A plain (non-fatal) ``RuntimeError`` is still caught so assignment
    continues for other issues.

These tests assert the *correct* behaviour, so they are RED against the
current buggy code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from crate_manager import CrateManager  # noqa: E402
from events import EventBus  # noqa: E402
from models import Crate  # noqa: E402
from subprocess_util import AuthenticationError, CreditExhaustedError  # noqa: E402
from tests.conftest import TaskFactory  # noqa: E402
from tests.helpers import ConfigFactory  # noqa: E402


def _make_manager() -> tuple[CrateManager, MagicMock, AsyncMock]:
    """Create a CrateManager with no active crate and mocked deps."""
    config = ConfigFactory.create()
    state = MagicMock()
    state.get_active_crate_number.return_value = None
    state.set_active_crate_number = MagicMock()
    pr_manager = AsyncMock()
    bus = EventBus()
    cm = CrateManager(config, state, pr_manager, bus)
    return cm, state, pr_manager


class TestCreditExhaustedPropagates:
    """Issue #6751 — CreditExhaustedError must not be silently swallowed
    by ``except RuntimeError`` in the milestone-assignment loop.
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6751 — fix not yet landed", strict=False)
    async def test_credit_exhausted_propagates_from_assignment_loop(self) -> None:
        """When ``set_issue_milestone`` raises ``CreditExhaustedError``,
        ``auto_package_if_needed`` must let it propagate rather than
        catching it silently.

        Currently FAILS (RED) because ``CreditExhaustedError`` is a
        ``RuntimeError`` subclass and the bare ``except RuntimeError``
        catches it.
        """
        # Arrange
        cm, _state, pr_mock = _make_manager()
        pr_mock.list_milestones.return_value = []
        pr_mock.create_milestone.return_value = Crate(number=10, title="2026-04-10.1")
        pr_mock.set_issue_milestone.side_effect = CreditExhaustedError(
            "usage limit reached"
        )
        task = TaskFactory.create(id=1, tags=["hydraflow-plan"])

        # Act & Assert — the error must escape
        with pytest.raises(CreditExhaustedError):
            await cm.auto_package_if_needed([task])


class TestAuthenticationErrorPropagates:
    """Issue #6751 — AuthenticationError must not be silently swallowed
    by ``except RuntimeError`` in the milestone-assignment loop.
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6751 — fix not yet landed", strict=False)
    async def test_authentication_error_propagates_from_assignment_loop(self) -> None:
        """When ``set_issue_milestone`` raises ``AuthenticationError``,
        ``auto_package_if_needed`` must let it propagate rather than
        catching it silently.

        Currently FAILS (RED) because ``AuthenticationError`` is a
        ``RuntimeError`` subclass and the bare ``except RuntimeError``
        catches it.
        """
        # Arrange
        cm, _state, pr_mock = _make_manager()
        pr_mock.list_milestones.return_value = []
        pr_mock.create_milestone.return_value = Crate(number=10, title="2026-04-10.1")
        pr_mock.set_issue_milestone.side_effect = AuthenticationError("Bad credentials")
        task = TaskFactory.create(id=1, tags=["hydraflow-plan"])

        # Act & Assert — the error must escape
        with pytest.raises(AuthenticationError):
            await cm.auto_package_if_needed([task])


class TestPlainRuntimeErrorStillCaught:
    """A non-fatal ``RuntimeError`` should still be caught so the loop
    continues assigning other issues.  This is GREEN on current code
    and must remain GREEN after the fix.
    """

    @pytest.mark.asyncio
    async def test_plain_runtime_error_does_not_propagate(self) -> None:
        """A transient API error (plain RuntimeError) is caught and the
        remaining issues still get assigned."""
        # Arrange
        cm, state_mock, pr_mock = _make_manager()
        pr_mock.list_milestones.return_value = []
        pr_mock.create_milestone.return_value = Crate(number=10, title="2026-04-10.1")
        pr_mock.set_issue_milestone.side_effect = [
            RuntimeError("transient API error"),
            None,  # second call succeeds
        ]
        task1 = TaskFactory.create(id=1, tags=["hydraflow-plan"])
        task2 = TaskFactory.create(id=2, tags=["hydraflow-plan"])

        # Act — should not raise
        await cm.auto_package_if_needed([task1, task2])

        # Assert — both calls attempted, crate still activated
        assert pr_mock.set_issue_milestone.call_count == 2
        state_mock.set_active_crate_number.assert_called_with(10)
