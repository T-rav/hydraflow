"""Wiki maintenance PR batching — kills the near-hourly treadmill.

2026-07-18/19: RepoWikiLoop opened a maintenance PR nearly every hour, each
carrying a handful of freshly synthesized entries (#9903/#9916/#9930/#9951…).
Every merge re-stales sibling PRs via the arch cascade. The batching contract:
below ``repo_wiki_min_batch_files`` the worktree changes are reverted and no
PR opens; the ``repo_wiki_max_batch_age_hours`` valve forces small dribbles to
land within a bounded window; every failure edge fails OPEN to the old
open-on-any-change behavior.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import repo_wiki_loop as rwl_module
from base_background_loop import LoopDeps
from repo_wiki import RepoWikiStore
from repo_wiki_loop import RepoWikiLoop, _parse_utc


def _make_loop(
    tmp_path: Path, *, min_files: int = 8, max_age: int = 24
) -> RepoWikiLoop:
    config = MagicMock()
    config.data_path.return_value = tmp_path / "queue"
    config.repo = "acme/widgets"
    config.repo_wiki_min_batch_files = min_files
    config.repo_wiki_max_batch_age_hours = max_age
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


def _git_worktree_with_changes(tmp_path: Path, n_files: int) -> Path:
    repo = tmp_path / "wt"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-q", "-m", "root"],
        check=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
        },
    )
    (repo / "repo_wiki").mkdir()
    for i in range(n_files):
        (repo / "repo_wiki" / f"entry-{i}.md").write_text("draft\n")
    return repo


class TestMaybeDeferSmallBatch:
    def test_small_batch_is_reverted_and_deferred(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path, min_files=8)
        wt = _git_worktree_with_changes(tmp_path, 3)

        deferred = loop._maybe_defer_small_batch(wt, "repo_wiki/", 3, False)

        assert deferred is True
        status = subprocess.run(
            ["git", "-C", str(wt), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert status == ""  # worktree fully reverted → helper sees no-diff

    def test_forced_by_age_never_defers(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path, min_files=8)
        wt = _git_worktree_with_changes(tmp_path, 3)

        assert loop._maybe_defer_small_batch(wt, "repo_wiki/", 3, True) is False

    def test_batch_at_threshold_is_not_deferred(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path, min_files=3)
        wt = _git_worktree_with_changes(tmp_path, 3)

        assert loop._maybe_defer_small_batch(wt, "repo_wiki/", 3, False) is False

    def test_revert_failure_fails_open_to_opening_the_pr(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path, min_files=8)
        missing = tmp_path / "not-a-git-repo"
        missing.mkdir()

        assert loop._maybe_defer_small_batch(missing, "repo_wiki/", 2, False) is False


class TestForcedByAge:
    @pytest.mark.asyncio
    async def test_stale_last_merge_forces_open(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop = _make_loop(tmp_path, max_age=24)
        old = (datetime.now(UTC) - timedelta(hours=30)).isoformat()
        monkeypatch.setattr(
            rwl_module,
            "run_subprocess",
            AsyncMock(return_value=json.dumps([{"mergedAt": old}])),
        )

        assert await loop._maintenance_batch_forced_by_age() is True

    @pytest.mark.asyncio
    async def test_recent_merge_does_not_force(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop = _make_loop(tmp_path, max_age=24)
        recent = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        monkeypatch.setattr(
            rwl_module,
            "run_subprocess",
            AsyncMock(return_value=json.dumps([{"mergedAt": recent}])),
        )

        assert await loop._maintenance_batch_forced_by_age() is False

    @pytest.mark.asyncio
    async def test_gh_error_and_no_history_fail_open(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop = _make_loop(tmp_path)
        monkeypatch.setattr(
            rwl_module, "run_subprocess", AsyncMock(side_effect=RuntimeError("boom"))
        )
        assert await loop._maintenance_batch_forced_by_age() is True

        monkeypatch.setattr(rwl_module, "run_subprocess", AsyncMock(return_value="[]"))
        assert await loop._maintenance_batch_forced_by_age() is True

    @pytest.mark.asyncio
    async def test_airgap_empty_repo_slug_fails_open(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        loop._config.repo = ""  # the #9754 air-gap lesson

        assert await loop._maintenance_batch_forced_by_age() is True


def test_parse_utc_handles_gh_zulu_and_garbage() -> None:
    parsed = _parse_utc("2026-07-19T02:31:31Z")
    assert parsed is not None and parsed.tzinfo is not None
    assert _parse_utc("") is None
    assert _parse_utc("not-a-date") is None
