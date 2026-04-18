"""Regression test for issue #6404.

Bug: ``EpicManager._execute_release`` only catches ``RuntimeError``.
Any non-RuntimeError exception (``KeyError``, ``TypeError``,
``ValueError``, ``AttributeError``, etc.) raised by ``release_epic()``
propagates out of the background task unhandled.

This means:
  - No ``EPIC_RELEASED(status="failed")`` event is published, so the UI
    hangs indefinitely waiting for a result that never arrives.
  - The asyncio task dies silently with an unhandled exception warning.

Expected behaviour after fix:
  - ALL exception types from ``_execute_release`` publish an
    ``EPIC_RELEASED(status="failed")`` event and clean up state.
  - ``_execute_release`` never raises — it is a background task that
    must always handle its own errors.

These tests assert the CORRECT (post-fix) behaviour and are therefore
RED against the current buggy code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

# Re-use the same builder pattern from test_epic.py
from epic import EpicManager
from events import EventType
from models import EpicState
from tests.conftest import make_state
from tests.helpers import ConfigFactory


def _make_epic_manager(tmp_path: Path) -> tuple[EpicManager, AsyncMock]:
    """Build an EpicManager with mocked deps; return (manager, bus)."""
    config = ConfigFactory.create(
        epic_label=["hydraflow-epic"],
        hitl_label=["hydraflow-hitl"],
    )
    state = make_state(tmp_path)
    prs = AsyncMock()
    fetcher = AsyncMock()
    fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])
    fetcher.fetch_issue_by_number = AsyncMock(return_value=None)
    bus = AsyncMock()
    bus.publish = AsyncMock()
    manager = EpicManager(config, state, prs, fetcher, bus)
    return manager, bus


class TestExecuteReleaseNonRuntimeError:
    """Non-RuntimeError exceptions in _execute_release must be caught."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exc_class,exc_msg",
        [
            (KeyError, "missing_key"),
            (TypeError, "unsupported operand"),
            (ValueError, "invalid value"),
            (AttributeError, "no attribute foo"),
        ],
        ids=["KeyError", "TypeError", "ValueError", "AttributeError"],
    )
    async def test_non_runtime_error_publishes_failure_event(
        self, tmp_path: Path, exc_class: type, exc_msg: str
    ) -> None:
        """A non-RuntimeError from release_epic must publish EPIC_RELEASED(failed).

        Current buggy code lets the exception escape, so no failure event
        is published.  This test is RED until the except clause is
        broadened beyond RuntimeError.
        """
        manager, bus = _make_epic_manager(tmp_path)
        manager._state.upsert_epic_state(EpicState(epic_number=100, child_issues=[1]))
        manager._release_jobs[100] = "job-1"

        # Make release_epic raise a non-RuntimeError
        manager.release_epic = AsyncMock(side_effect=exc_class(exc_msg))

        # _execute_release is a background task — it must NEVER raise
        await manager._execute_release(100, "job-1")

        # Verify that an EPIC_RELEASED failure event was published
        published_events = [
            c
            for c in bus.publish.call_args_list
            if hasattr(c.args[0], "type") and c.args[0].type == EventType.EPIC_RELEASED
        ]
        assert len(published_events) == 1, (
            f"Expected exactly one EPIC_RELEASED event for {exc_class.__name__}, "
            f"got {len(published_events)}"
        )
        payload = published_events[0].args[0].data
        assert payload["status"] == "failed"
        assert exc_msg in payload.get("error", "")

    @pytest.mark.asyncio
    async def test_non_runtime_error_does_not_raise(
        self,
        tmp_path: Path,
    ) -> None:
        """_execute_release must swallow non-RuntimeError exceptions.

        Current buggy code lets KeyError propagate — this test is RED.
        """
        manager, _bus = _make_epic_manager(tmp_path)
        manager._state.upsert_epic_state(EpicState(epic_number=100, child_issues=[1]))
        manager._release_jobs[100] = "job-1"
        manager.release_epic = AsyncMock(side_effect=KeyError("boom"))

        # Must not raise — background tasks that raise kill silently
        await manager._execute_release(100, "job-1")

    @pytest.mark.asyncio
    async def test_non_runtime_error_cleans_up_release_job(
        self,
        tmp_path: Path,
    ) -> None:
        """_release_jobs entry is removed even for non-RuntimeError.

        The finally block does clean this up, so this test should pass
        even on current code — it documents the expected invariant.
        """
        manager, _bus = _make_epic_manager(tmp_path)
        manager._state.upsert_epic_state(EpicState(epic_number=100, child_issues=[1]))
        manager._release_jobs[100] = "job-1"
        manager.release_epic = AsyncMock(side_effect=KeyError("boom"))

        # The finally block handles cleanup, but the exception propagates
        # past the except clause. We need to catch it to verify cleanup.
        try:
            await manager._execute_release(100, "job-1")
        except KeyError:
            pass  # Expected on buggy code

        assert 100 not in manager._release_jobs
