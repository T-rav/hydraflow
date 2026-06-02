"""Regression test for issue #6842.

``_hitl_routes.py:146`` fires ``asyncio.create_task(ctx.warm_hitl_summary(...))``
with no reference kept and no ``add_done_callback``.  Per Python docs, if this
task raises an exception it is only reported when the task is garbage-collected —
by then the log context is gone and the error surfaces as an opaque
"Task exception was never retrieved" warning on stderr.

The established convention in this codebase (see ``events.py:349-351``) is to:
1. Store the task reference in a ``set`` so it isn't GC'd prematurely.
2. Attach ``add_done_callback`` to log any exception.

These tests assert that the task created for ``warm_hitl_summary`` follows this
pattern — they will FAIL (RED) until the handler is fixed to add a done callback.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config import Credentials
from events import EventBus
from models import HITLItem
from tests.helpers import find_endpoint, make_dashboard_router

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_warm_conditions(config, state, tmp_path, event_bus):
    """Set up config/state so the create_task branch at line 146 fires.

    Conditions (lines 139-145 of _hitl_routes.py):
    - no cached summary for the issue
    - transcript_summarization_enabled = True
    - dry_run = False
    - credentials.gh_token is truthy
    - hitl_summary_retry_due returns True (no prior failure)
    """
    config.transcript_summarization_enabled = True
    config.dry_run = False
    creds = Credentials(gh_token="test-token")

    router, pr_mgr = make_dashboard_router(
        config, event_bus, state, tmp_path, credentials=creds
    )

    # A HITL item with NO cached summary → triggers warm path
    hitl_item = HITLItem(issue=99, title="Needs summary", pr=0)
    pr_mgr.list_hitl_items = AsyncMock(return_value=[hitl_item])

    return router, pr_mgr


# ===========================================================================
# Tests — fire-and-forget task must have a done callback
# ===========================================================================


class TestWarmHitlSummaryTaskTracking:
    """asyncio.create_task for warm_hitl_summary must add a done_callback.

    Without a done callback, exceptions from the background task are silently
    dropped — operators see stale/empty HITL summaries with no log trail.
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6842 — fix not yet landed", strict=False)
    async def test_task_has_done_callback(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """The task returned by create_task must have add_done_callback called.

        Currently FAILS because ``asyncio.create_task()`` at
        ``_hitl_routes.py:146`` discards the task reference and never
        registers a callback.
        """
        router, _pr_mgr = _setup_warm_conditions(config, state, tmp_path, event_bus)

        get_hitl = find_endpoint(router, "/api/hitl")
        assert get_hitl is not None

        # Return a mock Task so we can verify add_done_callback was called
        mock_task = MagicMock(spec=asyncio.Task)

        def fake_create_task(coro, **kwargs):
            # Close the coroutine to prevent "was never awaited" warning
            coro.close()
            return mock_task

        with patch(
            "dashboard_routes._hitl_routes.asyncio.create_task",
            side_effect=fake_create_task,
        ):
            await get_hitl()

        # The task MUST have a done_callback for exception logging.
        # This mirrors the established pattern from events.py:349-351.
        mock_task.add_done_callback.assert_called()

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6842 — fix not yet landed", strict=False)
    async def test_task_reference_is_stored(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """The task must be stored in a set to prevent premature GC.

        Fire-and-forget tasks with no strong reference can be garbage
        collected before completion.  The ``events.py`` pattern stores
        tasks in ``_pending_persists`` and discards them on completion.

        Currently FAILS because the task reference at ``_hitl_routes.py:146``
        is immediately discarded.
        """
        router, _pr_mgr = _setup_warm_conditions(config, state, tmp_path, event_bus)

        get_hitl = find_endpoint(router, "/api/hitl")
        assert get_hitl is not None

        created_tasks = []

        def capturing_create_task(coro, **kwargs):
            coro.close()
            task = MagicMock(spec=asyncio.Task)
            created_tasks.append(task)
            return task

        with patch(
            "dashboard_routes._hitl_routes.asyncio.create_task",
            side_effect=capturing_create_task,
        ):
            await get_hitl()

        assert len(created_tasks) == 1, "Expected one warm_hitl_summary task"

        # After the endpoint returns, the task should still have a strong
        # reference somewhere (e.g. a module-level set).  The only way to
        # verify this without inspecting internals is to confirm the
        # add_done_callback pattern is used (which includes the discard).
        # This assertion duplicates test_task_has_done_callback but frames
        # the requirement differently: the callback must include cleanup.
        created_tasks[0].add_done_callback.assert_called()
