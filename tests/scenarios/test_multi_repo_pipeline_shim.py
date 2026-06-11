"""Scenario: /api/pipeline aggregates real per-repo IssueStores under repo=__all__.

Complements ``test_multi_repo_aggregate_endpoints.py`` (which stubs the
orchestrator with a MagicMock snapshot) by driving the REAL
``get_pipeline_snapshot`` through the ``add_repo(with_pipeline=True)`` shim's
per-repo ``IssueStore`` — so the snapshot computation, the backend→frontend
stage remap, and the per-issue repo-tagging are exercised end to end against
colliding issue numbers, not mocked. The browser tier
(``test_multi_repo_pipeline_cards.py``) renders this; here it is asserted at the
fast API/scenario tier.
"""

from __future__ import annotations

import json

import pytest

from issue_store import STAGE_READY
from tests.helpers import find_endpoint, make_dashboard_router

pytestmark = pytest.mark.scenario


@pytest.mark.asyncio
async def test_pipeline_repo_all_aggregates_real_per_repo_stores(
    mock_world, config, event_bus, state, tmp_path
) -> None:
    mock_world.add_repo("owner/alpha", str(tmp_path / "alpha"), with_pipeline=True)
    mock_world.add_repo("owner/beta", str(tmp_path / "beta"), with_pipeline=True)
    # Issue #5 active in BOTH repos' real IssueStores — must survive as two cards.
    mock_world.registry.get("owner-alpha").orchestrator.issue_store.mark_active(
        5, STAGE_READY
    )
    mock_world.registry.get("owner-beta").orchestrator.issue_store.mark_active(
        5, STAGE_READY
    )

    router, _ = make_dashboard_router(
        config,
        event_bus,
        state,
        tmp_path,
        registry=mock_world.registry,
        default_repo_slug=config.repo.replace("/", "-"),
    )
    endpoint = find_endpoint(router, "/api/pipeline")

    data = json.loads((await endpoint(repo="__all__")).body)

    # backend "ready" maps to frontend "implement"; the colliding #5 survives
    # once per repo, each repo-tagged (real snapshot computation, not a mock).
    implement = data["stages"]["implement"]
    assert len(implement) == 2
    assert {i["issue_number"] for i in implement} == {5}
    assert {i["repo"] for i in implement} == {"owner-alpha", "owner-beta"}
