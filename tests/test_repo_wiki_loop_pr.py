"""Tests for the Phase 4 maintenance-PR path on ``RepoWikiLoop``.

Exercises ``_maybe_open_maintenance_pr`` and the module helpers
``_porcelain_paths`` + ``_maintenance_pr_body`` without reconstructing
the full loop lifecycle — instead stubs just the attributes the method
reads.  Matches the Phase 3.5 ``test_phase_wiki_wiring`` approach.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from auto_pr import AutoPrResult
from config import Credentials, HydraFlowConfig
from repo_wiki_loop import (
    RepoWikiLoop,
    _maintenance_pr_body,
    _porcelain_paths,
)
from wiki_maint_queue import MaintenanceQueue, MaintenanceTask


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A git repo at ``tmp_path`` with an initial commit and the
    tracked ``repo_wiki/`` dir present."""
    subprocess.run(["git", "init", str(tmp_path)], check=True)
    (tmp_path / "README.md").write_text("readme\n")
    (tmp_path / "repo_wiki").mkdir()
    (tmp_path / "repo_wiki" / "README.md").write_text("wiki readme\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-m",
            "init",
        ],
        check=True,
    )
    return tmp_path


def _make_config(
    repo_root: Path,
    *,
    auto_merge: bool = True,
    coalesce: bool = True,
) -> HydraFlowConfig:
    return HydraFlowConfig(
        repo="acme/widget",
        repo_root=repo_root,
        repo_wiki_git_backed=True,
        repo_wiki_path="repo_wiki",
        repo_wiki_maintenance_auto_merge=auto_merge,
        repo_wiki_maintenance_pr_coalesce=coalesce,
    )


def _stub_loop(
    config: HydraFlowConfig,
    *,
    credentials: Credentials | None = None,
    queue: MaintenanceQueue | None = None,
) -> RepoWikiLoop:
    """Build a ``RepoWikiLoop`` instance without running the real
    ``__init__`` — skipping ``BaseBackgroundLoop`` setup that pulls in
    the full dep graph.
    """
    loop = RepoWikiLoop.__new__(RepoWikiLoop)
    loop._config = config
    loop._credentials = credentials
    loop._queue = queue or MaintenanceQueue(path=config.repo_root / ".wmq.json")
    loop._open_pr_branch = None
    loop._open_pr_url = None
    return loop


class TestPorcelainPaths:
    def test_returns_empty_when_no_diff(self, git_repo: Path) -> None:
        assert _porcelain_paths(git_repo, "repo_wiki") == []

    def test_returns_untracked_files(self, git_repo: Path) -> None:
        (git_repo / "repo_wiki" / "new.md").write_text("new\n")
        paths = _porcelain_paths(git_repo, "repo_wiki")
        assert paths == ["repo_wiki/new.md"]

    def test_returns_modified_files(self, git_repo: Path) -> None:
        (git_repo / "repo_wiki" / "README.md").write_text("modified\n")
        paths = _porcelain_paths(git_repo, "repo_wiki")
        assert paths == ["repo_wiki/README.md"]

    def test_ignores_files_outside_prefix(self, git_repo: Path) -> None:
        (git_repo / "src").mkdir()
        (git_repo / "src" / "unrelated.py").write_text("# unrelated\n")
        assert _porcelain_paths(git_repo, "repo_wiki") == []


class TestMaintenancePrBody:
    def test_lists_actions_and_files(self) -> None:
        stats: dict[str, Any] = {
            "entries_marked_stale": 3,
            "entries_pruned": 1,
            "entries_compiled": 2,
            "queue_drained": 1,
        }
        body = _maintenance_pr_body(
            stats, ["repo_wiki/patterns/0001.md", "repo_wiki/gotchas/0002.md"]
        )
        assert "3 entries marked stale" in body
        assert "1 console-triggered tasks drained" in body
        assert "- `repo_wiki/patterns/0001.md`" in body
        assert "- `repo_wiki/gotchas/0002.md`" in body
        # Files are sorted for deterministic review output.
        gotchas_idx = body.index("repo_wiki/gotchas/0002.md")
        patterns_idx = body.index("repo_wiki/patterns/0001.md")
        assert gotchas_idx < patterns_idx


class TestMaybeOpenMaintenancePR:
    @pytest.mark.asyncio
    async def test_no_op_when_credentials_missing(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = False

        async def fake_open(**_: Any) -> AutoPrResult:
            nonlocal called
            called = True
            return AutoPrResult(status="opened", pr_url="x", branch="y")

        monkeypatch.setattr("repo_wiki_loop.open_automated_pr_async", fake_open)
        (git_repo / "repo_wiki" / "new.md").write_text("x\n")

        loop = _stub_loop(_make_config(git_repo), credentials=None)
        await loop._maybe_open_maintenance_pr({})

        assert called is False

    @pytest.mark.asyncio
    async def test_no_op_when_no_diff(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = False

        async def fake_open(**_: Any) -> AutoPrResult:
            nonlocal called
            called = True
            return AutoPrResult(status="opened", pr_url="x", branch="y")

        monkeypatch.setattr("repo_wiki_loop.open_automated_pr_async", fake_open)

        loop = _stub_loop(
            _make_config(git_repo),
            credentials=Credentials(gh_token="ghs_test"),
        )
        await loop._maybe_open_maintenance_pr({})

        assert called is False

    @pytest.mark.asyncio
    async def test_opens_pr_when_diff_exists(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        async def fake_open(**kwargs: Any) -> AutoPrResult:
            captured.update(kwargs)
            return AutoPrResult(
                status="opened",
                pr_url="https://github.com/x/y/pull/99",
                branch=kwargs["branch"],
            )

        monkeypatch.setattr("repo_wiki_loop.open_automated_pr_async", fake_open)
        (git_repo / "repo_wiki" / "new.md").write_text("new entry\n")

        stats: dict[str, Any] = {"entries_marked_stale": 2}
        loop = _stub_loop(
            _make_config(git_repo),
            credentials=Credentials(gh_token="ghs_test"),
        )
        await loop._maybe_open_maintenance_pr(stats)

        assert captured["gh_token"] == "ghs_test"
        assert captured["auto_merge"] is True
        assert captured["branch"].startswith("hydraflow/wiki-maint-")
        assert "chore(wiki): maintenance" in captured["pr_title"]
        assert captured["raise_on_failure"] is False
        assert loop._open_pr_url == "https://github.com/x/y/pull/99"
        assert stats["maintenance_pr"] == "https://github.com/x/y/pull/99"

    @pytest.mark.asyncio
    async def test_coalesces_into_open_pr_when_already_open(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_open = AsyncMock()
        monkeypatch.setattr("repo_wiki_loop.open_automated_pr_async", mock_open)
        (git_repo / "repo_wiki" / "new.md").write_text("new\n")

        loop = _stub_loop(
            _make_config(git_repo, coalesce=True),
            credentials=Credentials(gh_token="ghs_test"),
        )
        loop._open_pr_branch = "hydraflow/wiki-maint-prior"
        loop._open_pr_url = "https://github.com/x/y/pull/42"

        stats: dict[str, Any] = {}
        await loop._maybe_open_maintenance_pr(stats)

        mock_open.assert_not_called()
        assert stats["maintenance_pr"] == "https://github.com/x/y/pull/42"

    @pytest.mark.asyncio
    async def test_opens_new_pr_when_coalesce_disabled(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[dict[str, Any]] = []

        async def fake_open(**kwargs: Any) -> AutoPrResult:
            calls.append(kwargs)
            return AutoPrResult(
                status="opened", pr_url="https://x", branch=kwargs["branch"]
            )

        monkeypatch.setattr("repo_wiki_loop.open_automated_pr_async", fake_open)
        (git_repo / "repo_wiki" / "new.md").write_text("new\n")

        loop = _stub_loop(
            _make_config(git_repo, coalesce=False),
            credentials=Credentials(gh_token="ghs_test"),
        )
        loop._open_pr_branch = "hydraflow/wiki-maint-prior"  # existing

        await loop._maybe_open_maintenance_pr({})

        assert len(calls) == 1  # still opens a new PR

    @pytest.mark.asyncio
    async def test_pr_helper_failure_is_logged_not_raised(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_open(**kwargs: Any) -> AutoPrResult:
            return AutoPrResult(
                status="failed",
                pr_url=None,
                branch=kwargs["branch"],
                error="push rejected",
            )

        monkeypatch.setattr("repo_wiki_loop.open_automated_pr_async", fake_open)
        (git_repo / "repo_wiki" / "new.md").write_text("new\n")

        loop = _stub_loop(
            _make_config(git_repo),
            credentials=Credentials(gh_token="ghs_test"),
        )
        # Should not raise — keep the next tick alive.
        await loop._maybe_open_maintenance_pr({})
        assert loop._open_pr_branch is None


class TestQueueDrainIntegration:
    @pytest.mark.asyncio
    async def test_do_work_drains_queue_on_tick(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The loop drains the queue on every tick; Phase 4 logs the
        drain count in ``stats["queue_drained"]``."""
        from repo_wiki import RepoWikiStore

        # Prime the queue with two admin tasks.
        q_path = git_repo / ".queue.json"
        queue = MaintenanceQueue(path=q_path)
        queue.enqueue(
            MaintenanceTask(
                kind="force-compile",
                repo_slug="acme/widget",
                params={"topic": "patterns"},
            )
        )
        queue.enqueue(
            MaintenanceTask(
                kind="rebuild-index",
                repo_slug="acme/widget",
                params={},
            )
        )

        loop = _stub_loop(_make_config(git_repo), queue=queue)
        # Minimal attributes the real _do_work reads.
        loop._wiki_store = RepoWikiStore(git_repo / ".hydraflow" / "repo_wiki")
        loop._wiki_compiler = None
        loop._state = None

        # Stub _maybe_open_maintenance_pr so we don't try to open a PR.
        monkeypatch.setattr(loop, "_maybe_open_maintenance_pr", AsyncMock())

        stats = await loop._do_work()
        assert stats is not None
        assert stats["queue_drained"] == 2
        assert queue.peek() == []  # drained
