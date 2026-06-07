"""Multi-repo aggregation + per-repo scoping for GET /api/issues/history (Phase 2d).

Issue/PR numbers collide across repos, so the history endpoint must key rows by
``(repo, issue_number)`` and read each repo's OWN outcome/url, never the default
runtime's. These tests pin: ``repo=__all__`` unions colliding numbers without
collapsing them, ``repo=<slug>`` scopes to one runtime's own data, and a
per-repo request never reads or corrupts the default-repo history cache.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from events import EventBus, EventType, HydraFlowEvent
from models import IssueOutcomeType
from route_types import REPO_ALL
from state import StateTracker
from tests.helpers import (
    ConfigFactory,
    find_endpoint,
    make_dashboard_router,
    make_registry,
)


class _OfflineIssueFetcher:
    """Stand-in for IssueFetcher that never touches the network."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def fetch_issue_by_number(self, issue_number: int) -> None:
        return None


class _RepoAwareFetcher:
    """Fake IssueFetcher returning per-repo data so enrichment is observable."""

    def __init__(self, cfg: Any, *args: Any, **kwargs: Any) -> None:
        self._repo = cfg.repo

    async def fetch_issue_by_number(self, issue_number: int) -> SimpleNamespace:
        return SimpleNamespace(
            title=f"{self._repo} #{issue_number} ENRICHED",
            url=f"https://github.com/{self._repo}/issues/{issue_number}",
            labels=[],
            body="",
            milestone_number=None,
        )


@pytest.fixture(autouse=True)
def _offline_github(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep GitHub enrichment deterministic and offline for every test here."""
    monkeypatch.setattr("dashboard_routes._routes.IssueFetcher", _OfflineIssueFetcher)


async def _seed_runtime(
    tmp_path: Path,
    *,
    slug: str,
    repo: str,
    issue: int,
    outcome: IssueOutcomeType,
    pr: int = 0,
    enrichable: bool = False,
) -> dict[str, Any]:
    """Build a duck-typed runtime spec whose state holds *issue* with *outcome*.

    The issue row is created from an ISSUE_CREATED event on the runtime's own
    bus; ``enrichable=False`` seeds a title + epic so the row is NOT a GitHub
    enrichment candidate (no network), while the issue_url is left to come from
    the runtime's config so the closure-bug fix is observable.
    """
    cfg = ConfigFactory.create(repo=repo, repo_root=tmp_path / slug)
    bus = EventBus()
    st = StateTracker(tmp_path / f"{slug}-state.json")
    data: dict[str, Any] = {"issue": issue}
    if not enrichable:
        data["title"] = f"{slug} issue {issue}"
        data["labels"] = [f"epic:{slug}"]
    await bus.publish(HydraFlowEvent(type=EventType.ISSUE_CREATED, data=data))
    st.record_outcome(
        issue,
        outcome,
        reason=f"{slug} resolution",
        pr_number=pr or None,
        phase="review",
    )
    return {"slug": slug, "config": cfg, "state": st, "event_bus": bus}


@pytest.mark.asyncio
async def test_history_repo_all_unions_colliding_issue_numbers(
    config: Any, event_bus: Any, state: Any, tmp_path: Path
) -> None:
    """repo=__all__ keeps both repos' issue #42 with their distinct outcomes."""
    spec_a = await _seed_runtime(
        tmp_path,
        slug="owner-a",
        repo="owner/a",
        issue=42,
        outcome=IssueOutcomeType.MERGED,
        pr=101,
    )
    spec_b = await _seed_runtime(
        tmp_path,
        slug="owner-b",
        repo="owner/b",
        issue=42,
        outcome=IssueOutcomeType.HITL_APPROVED,
        pr=202,
    )
    registry = make_registry(spec_a, spec_b)
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, registry=registry
    )
    endpoint = find_endpoint(router, "/api/issues/history")

    payload = json.loads((await endpoint(repo=REPO_ALL, limit=500)).body)
    by_key = {(x["issue_number"], x["repo"]): x for x in payload["items"]}

    assert (42, "owner-a") in by_key
    assert (42, "owner-b") in by_key
    assert by_key[(42, "owner-a")]["outcome"]["outcome"] == "merged"
    assert by_key[(42, "owner-b")]["outcome"]["outcome"] == "hitl_approved"


@pytest.mark.asyncio
async def test_history_singular_repo_returns_its_own_outcome_url_and_tag(
    config: Any, event_bus: Any, state: Any, tmp_path: Path
) -> None:
    """repo=<slug> reads that runtime's outcome/url/tag, not the default's."""
    spec_a = await _seed_runtime(
        tmp_path,
        slug="owner-a",
        repo="owner/a",
        issue=42,
        outcome=IssueOutcomeType.MERGED,
        pr=101,
    )
    spec_b = await _seed_runtime(
        tmp_path,
        slug="owner-b",
        repo="owner/b",
        issue=42,
        outcome=IssueOutcomeType.HITL_APPROVED,
        pr=202,
    )
    registry = make_registry(spec_a, spec_b)
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, registry=registry
    )
    endpoint = find_endpoint(router, "/api/issues/history")

    payload = json.loads((await endpoint(repo="owner-b", limit=500)).body)
    item = next(x for x in payload["items"] if x["issue_number"] == 42)

    assert {x["repo"] for x in payload["items"]} == {"owner-b"}
    assert item["repo"] == "owner-b"
    assert item["outcome"] is not None
    assert item["outcome"]["outcome"] == "hitl_approved"
    assert "owner/b" in item["issue_url"]


@pytest.mark.asyncio
async def test_history_per_repo_request_does_not_corrupt_default_cache(
    config: Any, event_bus: Any, state: Any, tmp_path: Path
) -> None:
    """A repo=<slug> request must not read or overwrite the default cache."""
    await event_bus.publish(
        HydraFlowEvent(
            type=EventType.ISSUE_CREATED,
            data={"issue": 7, "title": "Host seven", "labels": ["epic:host"]},
        )
    )
    spec_b = await _seed_runtime(
        tmp_path,
        slug="owner-b",
        repo="owner/b",
        issue=42,
        outcome=IssueOutcomeType.HITL_APPROVED,
        pr=202,
        enrichable=True,
    )
    registry = make_registry(spec_b)
    router, _ = make_dashboard_router(
        config,
        event_bus,
        state,
        tmp_path,
        registry=registry,
        default_repo_slug="host",
    )
    endpoint = find_endpoint(router, "/api/issues/history")

    warm = json.loads((await endpoint(limit=100)).body)
    assert {x["issue_number"] for x in warm["items"]} == {7}

    await endpoint(repo="owner-b", limit=100)

    after = json.loads((await endpoint(limit=100)).body)
    assert {x["issue_number"] for x in after["items"]} == {7}


@pytest.mark.asyncio
async def test_outcomes_endpoint_scopes_and_tags_by_repo(
    config: Any, event_bus: Any, state: Any, tmp_path: Path
) -> None:
    """/api/issues/outcomes scopes to one repo and unions __all__ with tags."""
    spec_a = await _seed_runtime(
        tmp_path,
        slug="owner-a",
        repo="owner/a",
        issue=42,
        outcome=IssueOutcomeType.MERGED,
        pr=101,
    )
    spec_b = await _seed_runtime(
        tmp_path,
        slug="owner-b",
        repo="owner/b",
        issue=42,
        outcome=IssueOutcomeType.HITL_APPROVED,
        pr=202,
    )
    registry = make_registry(spec_a, spec_b)
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, registry=registry
    )
    endpoint = find_endpoint(router, "/api/issues/outcomes")

    agg = json.loads((await endpoint(repo=REPO_ALL)).body)
    assert agg["owner-a#42"]["outcome"] == "merged"
    assert agg["owner-a#42"]["repo"] == "owner-a"
    assert agg["owner-b#42"]["outcome"] == "hitl_approved"
    assert agg["owner-b#42"]["repo"] == "owner-b"

    scoped = json.loads((await endpoint(repo="owner-b")).body)
    assert scoped["42"]["outcome"] == "hitl_approved"
    assert scoped["42"]["repo"] == "owner-b"


@pytest.mark.asyncio
async def test_per_repo_request_enriches_despite_default_enriched_set(
    config: Any,
    event_bus: Any,
    state: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A repo=<slug> request enriches its own colliding issue number even after
    the default cache already marked that number enriched (no cross-repo skip)."""
    monkeypatch.setattr("dashboard_routes._routes.IssueFetcher", _RepoAwareFetcher)

    # Host/default: issue #42 with no title/epic -> an enrichment candidate.
    await event_bus.publish(
        HydraFlowEvent(type=EventType.ISSUE_CREATED, data={"issue": 42})
    )
    # Second repo: also issue #42, also an enrichment candidate.
    cfg_b = ConfigFactory.create(repo="owner/b", repo_root=tmp_path / "owner-b")
    bus_b = EventBus()
    state_b = StateTracker(tmp_path / "owner-b-state.json")
    await bus_b.publish(
        HydraFlowEvent(type=EventType.ISSUE_CREATED, data={"issue": 42})
    )
    registry = make_registry(
        {"slug": "owner-b", "config": cfg_b, "state": state_b, "event_bus": bus_b}
    )
    router, _ = make_dashboard_router(
        config,
        event_bus,
        state,
        tmp_path,
        registry=registry,
        default_repo_slug=config.repo.replace("/", "-"),
    )
    endpoint = find_endpoint(router, "/api/issues/history")

    # Warm the default cache: host #42 gets enriched, putting 42 in the default
    # runtime's enriched_issues set (keyed by bare number).
    warm = json.loads((await endpoint(limit=100)).body)
    host_item = next(x for x in warm["items"] if x["issue_number"] == 42)
    assert "ENRICHED" in host_item["title"]

    # owner-b's #42 must still be enriched — the default cache's enriched set
    # must not leak across repos and skip it.
    b_payload = json.loads((await endpoint(repo="owner-b", limit=100)).body)
    b_item = next(x for x in b_payload["items"] if x["issue_number"] == 42)
    assert "owner/b" in b_item["title"]
    assert "owner/b" in b_item["issue_url"]
