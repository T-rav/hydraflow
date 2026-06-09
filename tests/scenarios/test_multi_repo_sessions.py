"""Scenario: /api/sessions honours the None=default vs __all__=union invariant.

Drives the real route through a MockWorld-seeded registry of two isolated
``RepoRuntime`` objects (separate config / state / event bus per repo). Unlike
the duck-typed unit tests — which exercise the legacy no-registry single-state
filter — this proves the registry-present path end to end:

* ``repo=__all__`` unions every registered line's sessions, and
* a bare ``repo=None`` scopes to the *default* repo only (here the host repo is
  itself a registered runtime, as in a real deployment), rather than leaking the
  whole multi-repo set.
"""

from __future__ import annotations

import json

import pytest

from mockworld.seed import MockWorldSeed
from models import SessionLog
from tests.helpers import find_endpoint, make_dashboard_router

pytestmark = pytest.mark.scenario


def _session(repo: str, session_id: str) -> SessionLog:
    return SessionLog(
        id=session_id,
        repo=repo,
        started_at="2024-01-01T00:00:00Z",
        ended_at="2024-01-01T01:00:00Z",
        issues_processed=[1],
        issues_succeeded=1,
        issues_failed=0,
        status="completed",
    )


@pytest.mark.asyncio
async def test_sessions_all_unions_and_none_scopes_to_default(
    mock_world, tmp_path
) -> None:
    seed = MockWorldSeed(
        repos=[
            ("owner/alpha", str(tmp_path / "alpha")),
            ("owner/beta", str(tmp_path / "beta")),
        ],
    )
    mock_world.apply_seed(seed)

    alpha = mock_world.registry.get("owner-alpha")
    beta = mock_world.registry.get("owner-beta")
    alpha.state.save_session(_session("owner/alpha", "alpha-1"))
    beta.state.save_session(_session("owner/beta", "beta-1"))

    # Wire the host/default line to the alpha runtime, so the default repo is a
    # registered member of the registry (matching real multi-repo deployments).
    router, _ = make_dashboard_router(
        alpha.config,
        alpha.event_bus,
        alpha.state,
        tmp_path,
        registry=mock_world.registry,
        default_repo_slug="owner-alpha",
    )
    endpoint = find_endpoint(router, "/api/sessions")

    all_data = json.loads((await endpoint(repo="__all__")).body)
    assert {s["repo"] for s in all_data} == {"owner/alpha", "owner/beta"}

    none_data = json.loads((await endpoint(repo=None)).body)
    assert {s["repo"] for s in none_data} == {"owner/alpha"}
