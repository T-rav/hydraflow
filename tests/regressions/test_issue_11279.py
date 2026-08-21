"""Regression pin for #11279: the pipeline rail must not go confidently empty
during the post-restart boot window.

The bug: ``IssueStore._queues`` is populated with every backend stage key
mapped to an empty deque at construction time, *before* the first background
``refresh()`` ever runs. Right after a factory restart, a client's WS
reconnect triggers an immediate ``GET /api/pipeline`` poll (the reconnect
re-sync) that can land before that first ``refresh()`` completes.
``get_pipeline_snapshot()`` in that window returns every stage key present
but empty — byte-identical in shape to a genuinely empty pipeline — and the
frontend's PIPELINE_SNAPSHOT reducer treats any server snapshot as
authoritative, wiping rail cards that were actually just not-yet-fetched.

The fix: ``IssueStore.has_completed_initial_refresh`` tracks whether the
first refresh cycle has completed; ``/api/pipeline`` skips contributing a
not-yet-refreshed repo's stages and marks the response ``ready=False`` so
the client can hold its last-known state instead of reconciling against a
snapshot that was never real to begin with.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from events import EventBus
from issue_store import IssueStore
from tests.conftest import TaskFactory
from tests.helpers import (
    ConfigFactory,
    PipelineHarness,
    find_endpoint,
    make_dashboard_router,
)


def _make_store(fetch_result: list | None = None) -> IssueStore:
    fetcher = AsyncMock()
    fetcher.fetch_all = AsyncMock(return_value=fetch_result or [])
    return IssueStore(ConfigFactory.create(), fetcher, EventBus())


class TestHasCompletedInitialRefresh:
    """The readiness flag tracks the first successful refresh() cycle."""

    def test_starts_false_before_any_refresh(self) -> None:
        store = _make_store()
        assert store.has_completed_initial_refresh is False

    @pytest.mark.asyncio
    async def test_true_after_a_successful_refresh(self) -> None:
        store = _make_store()
        await store.refresh()
        assert store.has_completed_initial_refresh is True

    @pytest.mark.asyncio
    async def test_stays_false_when_the_fetcher_errors(self) -> None:
        fetcher = AsyncMock()
        fetcher.fetch_all = AsyncMock(side_effect=RuntimeError("gh CLI failed"))
        store = IssueStore(ConfigFactory.create(), fetcher, EventBus())

        await store.refresh()

        assert store.has_completed_initial_refresh is False


def test_pipeline_harness_direct_seed_is_authoritative(tmp_path) -> None:
    """The test harness's direct seed is its stand-in for initial refresh."""
    harness = PipelineHarness(tmp_path)
    assert harness.store.has_completed_initial_refresh is False

    harness.seed_issue(TaskFactory.create(id=42), stage="find")

    assert harness.store.has_completed_initial_refresh is True
    assert [
        entry["issue_number"]
        for entry in harness.store.get_pipeline_snapshot()["find"]
    ] == [42]


class TestPipelineRouteReadinessGate:
    """GET /api/pipeline must not surface a not-yet-refreshed store as empty."""

    @pytest.mark.asyncio
    async def test_not_ready_store_reports_ready_false_and_no_stages(
        self, config, event_bus, state, tmp_path
    ) -> None:
        store = _make_store()
        orch = SimpleNamespace(running=True, pipeline_enabled=True, issue_store=store)
        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: orch
        )
        endpoint = find_endpoint(router, "/api/pipeline")
        assert endpoint is not None

        payload = json.loads((await endpoint(repo=None)).body)

        assert payload["ready"] is False
        # Not a single stage key present — an empty *and* keyed response is
        # exactly the trap shape that used to look like "genuinely empty".
        assert payload["stages"] == {}

    @pytest.mark.asyncio
    async def test_ready_store_reports_ready_true_with_real_data(
        self, config, event_bus, state, tmp_path
    ) -> None:
        store = _make_store([TaskFactory.create(id=42, tags=["hydraflow-find"])])
        await store.refresh()

        orch = SimpleNamespace(running=True, pipeline_enabled=True, issue_store=store)
        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: orch
        )
        endpoint = find_endpoint(router, "/api/pipeline")
        assert endpoint is not None

        payload = json.loads((await endpoint(repo=None)).body)

        assert payload["ready"] is True
        assert [i["issue_number"] for i in payload["stages"]["triage"]] == [42]
