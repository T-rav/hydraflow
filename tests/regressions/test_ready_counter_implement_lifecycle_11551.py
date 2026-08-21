"""Regression pins: READY counters see the implement lifecycle (#11551).

``ImplementPhase`` wraps every build in ``store_lifecycle(store, n,
"implement")`` — the dashboard-facing phase name — while ``IssueStore`` keys
``active_count`` / ``total_processed`` on the internal ``IssueStoreStage``
value ``"ready"``. ``mark_active`` stored the string verbatim, so a running
implementer contributed to NO counter (``/api/queue`` ``active_count.ready``
stayed 0) and its completion was silently dropped from
``total_processed.ready`` (observed live on #11518).

These pins drive the REAL ``store_lifecycle`` helper with the REAL
``"implement"`` argument against a real ``IssueStore`` and read the result
back through the store and through the ``/api/queue`` route.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from events import EventBus
from issue_store import STAGE_READY, IssueStore
from phase_utils import store_lifecycle
from tests.helpers import ConfigFactory, find_endpoint, make_dashboard_router

_ISSUE = 11518


def _store() -> IssueStore:
    return IssueStore(ConfigFactory.create(), AsyncMock(), EventBus())


@pytest.mark.asyncio
async def test_store_lifecycle_implement_is_counted_as_ready() -> None:
    store = _store()

    async with store_lifecycle(store, _ISSUE, "implement"):
        during = store.get_queue_stats()
        assert during.active_count[STAGE_READY] == 1
        assert during.total_processed[STAGE_READY] == 0

    after = store.get_queue_stats()
    assert after.active_count[STAGE_READY] == 0
    assert after.total_processed[STAGE_READY] == 1


@pytest.mark.asyncio
async def test_api_queue_reports_one_active_implementer(
    config, event_bus, state, tmp_path
) -> None:
    store = _store()
    router, _ = make_dashboard_router(
        config,
        event_bus,
        state,
        tmp_path,
        get_orch=lambda: SimpleNamespace(
            issue_store=store, running=True, pipeline_enabled=True
        ),
    )
    endpoint = find_endpoint(router, "/api/queue")

    async with store_lifecycle(store, _ISSUE, "implement"):
        during = json.loads((await endpoint()).body)
        assert during["active_count"]["ready"] == 1

    after = json.loads((await endpoint()).body)
    assert after["active_count"]["ready"] == 0
    assert after["total_processed"]["ready"] == 1
