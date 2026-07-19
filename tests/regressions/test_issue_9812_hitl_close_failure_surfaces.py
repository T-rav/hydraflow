"""Regression: HITL close/skip silently 'succeeded' on gh failures (#9812).

``PRManager.close_issue``/``close_pr`` swallowed the gh RuntimeError and
returned normally, so ``/api/hitl/{n}/close`` and ``/skip`` ran their local
cleanup (row removed, outcome recorded, comment posted) while the issue
stayed OPEN on GitHub — the row vanished and reappeared on refresh, with the
HITL counter stuck.

Contract pinned here: the port methods return bool; on False the routes
return HTTP 502, run ZERO local cleanup, and leave the row in the queue —
the UI tells the truth.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from models import HITLCloseRequest, HITLSkipRequest
from tests.helpers import find_endpoint, make_dashboard_router


def _router_with_failing_close(config, event_bus, state, tmp_path):
    mock_orch = MagicMock()
    mock_orch.skip_hitl_issue = MagicMock()
    router, pr_mgr = make_dashboard_router(
        config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
    )
    pr_mgr.close_issue = AsyncMock(return_value=False)  # gh call failed
    pr_mgr.post_comment = AsyncMock()
    pr_mgr.remove_label = AsyncMock()
    pr_mgr.add_labels = AsyncMock()
    pr_mgr.swap_pipeline_labels = AsyncMock()
    return router, pr_mgr, mock_orch


@pytest.mark.asyncio
async def test_close_route_returns_502_and_skips_local_cleanup(
    config, event_bus, state, tmp_path
) -> None:
    router, pr_mgr, mock_orch = _router_with_failing_close(
        config, event_bus, state, tmp_path
    )

    close = find_endpoint(router, "/api/hitl/{issue_number}/close")
    assert close is not None
    response = await close(42, HITLCloseRequest(reason="obsolete"))

    assert response.status_code == 502
    detail = json.loads(response.body)
    assert "left in the HITL queue" in detail["detail"]
    pr_mgr.post_comment.assert_not_awaited()  # no cleanup ran
    mock_orch.skip_hitl_issue.assert_not_called()


@pytest.mark.asyncio
async def test_skip_route_returns_502_and_skips_local_cleanup(
    config, event_bus, state, tmp_path
) -> None:
    state.set_hitl_origin(42, "hydraflow-review")
    router, pr_mgr, mock_orch = _router_with_failing_close(
        config, event_bus, state, tmp_path
    )

    skip = find_endpoint(router, "/api/hitl/{issue_number}/skip")
    assert skip is not None
    response = await skip(42, HITLSkipRequest(reason="not needed"))

    assert response.status_code == 502
    pr_mgr.post_comment.assert_not_awaited()
    mock_orch.skip_hitl_issue.assert_not_called()


@pytest.mark.asyncio
async def test_successful_close_still_resolves_the_item(
    config, event_bus, state, tmp_path
) -> None:
    router, pr_mgr, mock_orch = _router_with_failing_close(
        config, event_bus, state, tmp_path
    )
    pr_mgr.close_issue = AsyncMock(return_value=True)

    close = find_endpoint(router, "/api/hitl/{issue_number}/close")
    assert close is not None
    response = await close(42, HITLCloseRequest(reason="done"))

    assert response.status_code == 200
    pr_mgr.close_issue.assert_awaited_once_with(42)
