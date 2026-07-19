"""Regression: RepoWikiLoop coalesce state lost on restart (#9894).

``_open_pr_branch``/``_open_pr_url`` are process-local, so a factory restart
forgot an open ``hydraflow-wiki-maintenance`` PR and the next tick opened a
duplicate (2026-07-18: three same-day maintenance PRs coexisted; two rotted
CONFLICTING+HITL and were closed by hand). These tests pin the adopt-on-boot
contract: with nothing tracked, the loop rediscovers the newest open
maintenance PR from GitHub (the source of truth) before deciding to heal,
and every failure edge degrades to the pre-guard behavior.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import repo_wiki_loop as rwl_module
from base_background_loop import LoopDeps
from repo_wiki import RepoWikiStore
from repo_wiki_loop import RepoWikiLoop


def _make_loop(tmp_path: Path) -> RepoWikiLoop:
    config = MagicMock()
    config.data_path.return_value = tmp_path / "queue"
    config.repo = "acme/widgets"
    config.repo_wiki_maintenance_pr_coalesce = True
    deps = LoopDeps(
        event_bus=MagicMock(),
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=MagicMock(return_value=True),
        sleep_fn=MagicMock(),
        interval_cb=None,
    )
    loop = RepoWikiLoop(
        config=config, wiki_store=RepoWikiStore(tmp_path / "wiki"), deps=deps
    )
    creds = MagicMock()
    creds.gh_token = "tok"
    loop._credentials = creds
    return loop


def _rows(*numbers: int) -> str:
    return json.dumps(
        [
            {
                "number": n,
                "url": f"https://github.com/acme/widgets/pull/{n}",
                "headRefName": f"hydraflow/wiki-maint-{n}",
            }
            for n in numbers
        ]
    )


@pytest.mark.asyncio
async def test_restart_adopts_newest_open_maintenance_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop = _make_loop(tmp_path)
    monkeypatch.setattr(
        rwl_module, "run_subprocess", AsyncMock(return_value=_rows(7, 12))
    )
    stats: dict[str, Any] = {}

    await loop._adopt_open_maintenance_pr(stats)

    assert loop._open_pr_url == "https://github.com/acme/widgets/pull/12"
    assert loop._open_pr_branch == "hydraflow/wiki-maint-12"
    assert stats["maintenance_pr_adopted"] == loop._open_pr_url


@pytest.mark.asyncio
async def test_nothing_open_leaves_state_untracked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop = _make_loop(tmp_path)
    monkeypatch.setattr(rwl_module, "run_subprocess", AsyncMock(return_value="[]"))

    await loop._adopt_open_maintenance_pr({})

    assert loop._open_pr_branch is None
    assert loop._open_pr_url is None


@pytest.mark.asyncio
async def test_gh_failure_is_fail_soft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop = _make_loop(tmp_path)
    monkeypatch.setattr(
        rwl_module,
        "run_subprocess",
        AsyncMock(side_effect=RuntimeError("gh exploded")),
    )

    await loop._adopt_open_maintenance_pr({})  # must not raise

    assert loop._open_pr_branch is None


@pytest.mark.asyncio
async def test_tracked_state_or_empty_repo_never_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe = AsyncMock(return_value=_rows(3))
    monkeypatch.setattr(rwl_module, "run_subprocess", probe)

    tracked = _make_loop(tmp_path)
    tracked._open_pr_branch = "hydraflow/wiki-maint-3"
    await tracked._adopt_open_maintenance_pr({})

    airgapped = _make_loop(tmp_path)  # the #9754 lesson: empty repo slug
    airgapped._config.repo = ""
    await airgapped._adopt_open_maintenance_pr({})

    probe.assert_not_awaited()
