"""Scenario: the dashboard's terminal buckets carry the real store's status vocabulary.

Regression for #10515: ``FakeIssueStore.get_pipeline_snapshot`` stamped its
STAGE_HITL and STAGE_MERGED buckets with ``PipelineIssueStatus.PROCESSING``
while the real ``IssueStore`` stamps ``"hitl"`` / ``"merged"``. A MockWorld
scenario asserting on terminal-bucket status through the actual
``GET /api/pipeline`` route — the same handler production traffic hits —
would have passed against the buggy Fake and given false confidence that the
dashboard's terminal-bucket status mapping was under test.

This drives the real route handler with a ``FakeIssueStore`` wired as the
orchestrator's issue store (mirroring how ``MockWorld._build_wired_orchestrator``
wires it for the in-process dashboard), so it exercises the full path: Fake ->
route -> ``PipelineIssue.model_validate`` -> JSON, not just the Fake in
isolation.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from mockworld.fakes.fake_issue_store import FakeIssueStore
from tests.helpers import find_endpoint, make_dashboard_router

pytestmark = pytest.mark.scenario


@pytest.mark.asyncio
async def test_pipeline_route_reports_hitl_and_merged_status_not_processing(
    mock_world, config, event_bus, state, tmp_path
) -> None:
    mock_world.github.add_issue(1, "needs a human", "body", labels=["hydraflow-hitl"])
    mock_world.github.add_issue(2, "shipped", "body", labels=[])
    store = FakeIssueStore(github=mock_world.github, event_bus=event_bus)
    store.mark_merged(2)

    orch = SimpleNamespace(running=True, pipeline_enabled=True, issue_store=store)
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, get_orch=lambda: orch
    )
    endpoint = find_endpoint(router, "/api/pipeline")

    data = json.loads((await endpoint(repo=None)).body)

    hitl_entries = data["stages"]["hitl"]
    assert len(hitl_entries) == 1
    assert hitl_entries[0]["status"] == "hitl"

    merged_entries = data["stages"]["merged"]
    assert len(merged_entries) == 1
    assert merged_entries[0]["status"] == "merged"
