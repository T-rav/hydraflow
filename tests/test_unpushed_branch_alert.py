"""Unit tests for the boot-time unpushed-local-branch check (#10011 part 2).

Covers the real ``git for-each-ref`` scan against an actual repo (the
#9965 regression-collection shape: a local branch ahead of its own
upstream), the no-network/non-git-dir failure path, and the
log+publish-once-if-found alerting contract.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from branch_gc_scan import UnpushedBranch
from config import HydraFlowConfig
from events import EventBus, EventType
from unpushed_branch_alert import (
    check_and_alert_unpushed_branches,
    scan_unpushed_local_branches,
)


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)  # noqa: S603


def _init_repo_with_unpushed_commit(tmp_path: Path) -> Path:
    """Build a local repo + bare 'origin' where the local branch is ahead by 1.

    Mirrors the real #9965 shape: a branch tracking origin/<branch> that has
    a commit the remote doesn't have.
    """
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _run(["git", "init", "--bare", "-b", "main", str(origin)], cwd=tmp_path)

    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-b", "main", str(repo)], cwd=tmp_path)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "config", "user.name", "Test"], cwd=repo)
    (repo / "f.txt").write_text("one\n", encoding="utf-8")
    _run(["git", "add", "f.txt"], cwd=repo)
    _run(["git", "commit", "-m", "initial"], cwd=repo)
    _run(["git", "remote", "add", "origin", str(origin)], cwd=repo)
    _run(["git", "push", "-u", "origin", "main"], cwd=repo)

    # One more local commit that never gets pushed — the unpushed-work shape.
    (repo / "f.txt").write_text("one\ntwo\n", encoding="utf-8")
    _run(["git", "add", "f.txt"], cwd=repo)
    _run(["git", "commit", "-m", "unpushed fix"], cwd=repo)
    return repo


class TestScanUnpushedLocalBranches:
    async def test_finds_branch_ahead_of_its_upstream(self, tmp_path: Path) -> None:
        repo = _init_repo_with_unpushed_commit(tmp_path)

        result = await scan_unpushed_local_branches(repo)

        assert len(result) == 1
        assert result[0].branch == "main"
        assert result[0].ahead == 1

    async def test_clean_repo_reports_nothing(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin.git"
        origin.mkdir()
        _run(["git", "init", "--bare", "-b", "main", str(origin)], cwd=tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()
        _run(["git", "init", "-b", "main", str(repo)], cwd=tmp_path)
        _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
        _run(["git", "config", "user.name", "Test"], cwd=repo)
        (repo / "f.txt").write_text("one\n", encoding="utf-8")
        _run(["git", "add", "f.txt"], cwd=repo)
        _run(["git", "commit", "-m", "initial"], cwd=repo)
        _run(["git", "remote", "add", "origin", str(origin)], cwd=repo)
        _run(["git", "push", "-u", "origin", "main"], cwd=repo)

        result = await scan_unpushed_local_branches(repo)

        assert result == []

    async def test_non_git_directory_returns_empty_not_raise(
        self, tmp_path: Path
    ) -> None:
        not_a_repo = tmp_path / "plain"
        not_a_repo.mkdir()

        result = await scan_unpushed_local_branches(not_a_repo)

        assert result == []


class TestCheckAndAlertUnpushedBranches:
    def _config(self, tmp_path: Path) -> HydraFlowConfig:
        return HydraFlowConfig(
            data_root=tmp_path / "data",
            repo_root=tmp_path / "repo",
            repo="owner/repo",
        )

    async def test_clean_scan_publishes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "unpushed_branch_alert.scan_unpushed_local_branches",
            AsyncMock(return_value=[]),
        )
        bus = EventBus()
        published = []
        bus.publish = AsyncMock(side_effect=published.append)  # type: ignore[method-assign]

        result = await check_and_alert_unpushed_branches(self._config(tmp_path), bus)

        assert result == []
        assert published == []

    async def test_found_branches_log_warning_and_publish_one_alert(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        found = [UnpushedBranch(branch="main", upstream="origin/main", ahead=1)]
        monkeypatch.setattr(
            "unpushed_branch_alert.scan_unpushed_local_branches",
            AsyncMock(return_value=found),
        )
        bus = EventBus()
        published = []
        bus.publish = AsyncMock(side_effect=published.append)  # type: ignore[method-assign]

        with caplog.at_level("WARNING"):
            result = await check_and_alert_unpushed_branches(
                self._config(tmp_path), bus
            )

        assert result == found
        assert any("unpushed" in rec.message.lower() for rec in caplog.records)
        assert len(published) == 1
        event = published[0]
        assert event.type == EventType.SYSTEM_ALERT
        assert event.data["kind"] == "unpushed_local_branches"
        assert event.data["branches"] == ["main"]

    async def test_none_event_bus_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        found = [UnpushedBranch(branch="main", upstream="origin/main", ahead=1)]
        monkeypatch.setattr(
            "unpushed_branch_alert.scan_unpushed_local_branches",
            AsyncMock(return_value=found),
        )

        result = await check_and_alert_unpushed_branches(self._config(tmp_path), None)

        assert result == found

    async def test_publish_failure_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        found = [UnpushedBranch(branch="main", upstream="origin/main", ahead=1)]
        monkeypatch.setattr(
            "unpushed_branch_alert.scan_unpushed_local_branches",
            AsyncMock(return_value=found),
        )
        bus = EventBus()
        bus.publish = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]

        result = await check_and_alert_unpushed_branches(self._config(tmp_path), bus)

        assert result == found
