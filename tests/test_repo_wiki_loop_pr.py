"""Tests for the Phase 4 maintenance-PR path on ``RepoWikiLoop``.

Exercises ``_heal_and_open_maintenance_pr`` (the #9539 generate-in-worktree
heal+PR) and the module helpers ``_porcelain_paths`` + ``_maintenance_pr_body``
without reconstructing the full loop lifecycle — instead stubs just the
attributes the method reads.  Matches the Phase 3.5 ``test_phase_wiki_wiring``
approach.
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
    loop._worker_name = "repo_wiki"
    loop._enabled_cb = lambda _name: True
    # _tribal_store is set in RepoWikiLoop.__init__; since __new__ bypasses
    # __init__, stub it as None so the direct attr read in _do_work doesn't
    # AttributeError (the call site is None-safe — generalization pass is
    # skipped when tribal_store is None).
    loop._tribal_store = None
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


class TestHealAndOpenMaintenancePR:
    """``_heal_and_open_maintenance_pr`` runs the heal INSIDE the ephemeral
    worktree (via ``generate_and_open_pr_async``) and never touches
    ``repo_root`` (#9539). These tests mock the PR helper to assert the
    orchestration; the actual heal+clean-checkout invariant is covered by
    ``test_heal_leaves_repo_root_clean_real_git`` below.
    """

    @pytest.mark.asyncio
    async def test_no_op_when_credentials_missing(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = False

        async def fake_gen(**_: Any) -> AutoPrResult:
            nonlocal called
            called = True
            return AutoPrResult(status="opened", pr_url="x", branch="y")

        monkeypatch.setattr("repo_wiki_loop.generate_and_open_pr_async", fake_gen)

        loop = _stub_loop(_make_config(git_repo), credentials=None)
        await loop._heal_and_open_maintenance_pr(set(), {})

        assert called is False

    @pytest.mark.asyncio
    async def test_no_op_when_not_a_git_repo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = False

        async def fake_gen(**_: Any) -> AutoPrResult:
            nonlocal called
            called = True
            return AutoPrResult(status="opened", pr_url="x", branch="y")

        monkeypatch.setattr("repo_wiki_loop.generate_and_open_pr_async", fake_gen)
        non_git = tmp_path / "plain"
        non_git.mkdir()

        loop = _stub_loop(
            _make_config(non_git), credentials=Credentials(gh_token="ghs_test")
        )
        await loop._heal_and_open_maintenance_pr(set(), {})

        assert called is False

    @pytest.mark.asyncio
    async def test_opens_pr_with_expected_args_and_tracks_branch(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        async def fake_gen(**kwargs: Any) -> AutoPrResult:
            captured.update(kwargs)
            return AutoPrResult(
                status="opened",
                pr_url="https://github.com/x/y/pull/99",
                branch=kwargs["branch"],
            )

        monkeypatch.setattr("repo_wiki_loop.generate_and_open_pr_async", fake_gen)

        stats: dict[str, Any] = {"queue_drained": 0}
        loop = _stub_loop(
            _make_config(git_repo),
            credentials=Credentials(gh_token="ghs_test"),
        )
        await loop._heal_and_open_maintenance_pr(set(), stats)

        assert captured["gh_token"] == "ghs_test"
        # Auto-merge is off — the loop reviews + merges itself after CI green.
        assert captured["auto_merge"] is False
        # The heal generates straight into the worktree's tracked layout.
        assert captured["path_specs"] == ["repo_wiki"]
        assert captured["labels"] == ["hydraflow-wiki-maintenance"]
        assert captured["raise_on_failure"] is False
        assert captured["branch"].startswith("hydraflow/wiki-maint-")
        assert "chore(wiki): maintenance" in captured["pr_title"]
        # The body + the file-state generator are both deferred callables.
        assert callable(captured["pr_body"])
        assert callable(captured["generate"])
        assert loop._open_pr_url == "https://github.com/x/y/pull/99"
        assert loop._open_pr_branch == captured["branch"]
        assert stats["maintenance_pr"] == "https://github.com/x/y/pull/99"

    @pytest.mark.asyncio
    async def test_no_diff_result_opens_no_pr(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_gen(**kwargs: Any) -> AutoPrResult:
            return AutoPrResult(status="no-diff", pr_url=None, branch=kwargs["branch"])

        monkeypatch.setattr("repo_wiki_loop.generate_and_open_pr_async", fake_gen)

        loop = _stub_loop(
            _make_config(git_repo),
            credentials=Credentials(gh_token="ghs_test"),
        )
        await loop._heal_and_open_maintenance_pr(set(), {})

        # No diff → no PR tracked, so the next tick heals again.
        assert loop._open_pr_branch is None
        assert loop._open_pr_url is None

    @pytest.mark.asyncio
    async def test_pr_helper_failure_is_logged_not_raised(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_gen(**kwargs: Any) -> AutoPrResult:
            return AutoPrResult(
                status="failed",
                pr_url=None,
                branch=kwargs["branch"],
                error="push rejected",
            )

        monkeypatch.setattr("repo_wiki_loop.generate_and_open_pr_async", fake_gen)

        loop = _stub_loop(
            _make_config(git_repo),
            credentials=Credentials(gh_token="ghs_test"),
        )
        # Should not raise — keep the next tick alive.
        await loop._heal_and_open_maintenance_pr(set(), {})
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

        # Stub both async PR hooks so we don't try to open/poll a PR.
        monkeypatch.setattr(loop, "_heal_and_open_maintenance_pr", AsyncMock())
        monkeypatch.setattr(loop, "_poll_and_merge_open_pr", AsyncMock())

        stats = await loop._do_work()
        assert stats is not None
        assert stats["queue_drained"] == 2
        assert queue.peek() == []  # drained


class TestPollAndMergeOpenPR:
    @pytest.mark.asyncio
    async def test_no_op_when_nothing_tracked(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = False

        async def fake_run(*args: Any, **kwargs: Any) -> str:
            del args, kwargs
            nonlocal called
            called = True
            return ""

        monkeypatch.setattr("repo_wiki_loop.run_subprocess", fake_run)

        loop = _stub_loop(
            _make_config(git_repo),
            credentials=Credentials(gh_token="ghs_test"),
        )
        await loop._poll_and_merge_open_pr({})
        assert called is False

    @pytest.mark.asyncio
    async def test_clears_state_when_pr_already_merged(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, ...]] = []

        async def fake_run(*cmd: Any, **_: Any) -> str:
            calls.append(tuple(str(c) for c in cmd))
            if cmd[:3] == ("gh", "pr", "view"):
                return '{"state":"MERGED","reviewDecision":"APPROVED","statusCheckRollup":[{"conclusion":"SUCCESS"}]}'
            return ""

        monkeypatch.setattr("repo_wiki_loop.run_subprocess", fake_run)

        loop = _stub_loop(
            _make_config(git_repo),
            credentials=Credentials(gh_token="ghs_test"),
        )
        loop._open_pr_url = "https://github.com/x/y/pull/9"
        loop._open_pr_branch = "hydraflow/wiki-maint-xyz"

        stats: dict[str, Any] = {}
        await loop._poll_and_merge_open_pr(stats)

        # gh pr view called, merge NOT called again (already merged).
        assert any(c[:3] == ("gh", "pr", "view") for c in calls)
        assert not any(c[:3] == ("gh", "pr", "merge") for c in calls)
        assert loop._open_pr_url is None
        assert stats["maintenance_pr_state"] == "MERGED"

    @pytest.mark.asyncio
    async def test_skips_when_ci_pending(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_run(*cmd: Any, **_: Any) -> str:
            if cmd[:3] == ("gh", "pr", "view"):
                # CI is in-progress / queued.
                return (
                    '{"state":"OPEN","reviewDecision":null,'
                    '"statusCheckRollup":[{"conclusion":"","state":"PENDING"}]}'
                )
            raise AssertionError(f"unexpected cmd {cmd}")

        monkeypatch.setattr("repo_wiki_loop.run_subprocess", fake_run)

        loop = _stub_loop(
            _make_config(git_repo),
            credentials=Credentials(gh_token="ghs_test"),
        )
        loop._open_pr_url = "https://github.com/x/y/pull/10"

        stats: dict[str, Any] = {}
        await loop._poll_and_merge_open_pr(stats)

        assert stats["maintenance_pr_ci"] == "pending"
        assert loop._open_pr_url == "https://github.com/x/y/pull/10"  # retained

    @pytest.mark.asyncio
    async def test_approves_then_merges_when_ci_green(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, ...]] = []

        async def fake_run(*cmd: Any, **_: Any) -> str:
            calls.append(tuple(str(c) for c in cmd))
            if cmd[:3] == ("gh", "pr", "view"):
                return (
                    '{"state":"OPEN","reviewDecision":null,'
                    '"statusCheckRollup":[{"conclusion":"SUCCESS"}]}'
                )
            return ""

        monkeypatch.setattr("repo_wiki_loop.run_subprocess", fake_run)

        loop = _stub_loop(
            _make_config(git_repo),
            credentials=Credentials(gh_token="ghs_test"),
        )
        loop._open_pr_url = "https://github.com/x/y/pull/11"
        loop._open_pr_branch = "hydraflow/wiki-maint-abc"

        stats: dict[str, Any] = {}
        await loop._poll_and_merge_open_pr(stats)

        # Approve then merge.
        review_idx = next(
            i for i, c in enumerate(calls) if c[:3] == ("gh", "pr", "review")
        )
        merge_idx = next(
            i for i, c in enumerate(calls) if c[:3] == ("gh", "pr", "merge")
        )
        assert review_idx < merge_idx
        assert "--approve" in calls[review_idx]
        assert "--squash" in calls[merge_idx]
        assert loop._open_pr_url is None  # cleared after merge
        assert stats["maintenance_pr_state"] == "MERGED"

    @pytest.mark.asyncio
    async def test_skips_approve_when_already_approved(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, ...]] = []

        async def fake_run(*cmd: Any, **_: Any) -> str:
            calls.append(tuple(str(c) for c in cmd))
            if cmd[:3] == ("gh", "pr", "view"):
                return (
                    '{"state":"OPEN","reviewDecision":"APPROVED",'
                    '"statusCheckRollup":[{"conclusion":"SUCCESS"}]}'
                )
            return ""

        monkeypatch.setattr("repo_wiki_loop.run_subprocess", fake_run)

        loop = _stub_loop(
            _make_config(git_repo),
            credentials=Credentials(gh_token="ghs_test"),
        )
        loop._open_pr_url = "https://github.com/x/y/pull/12"

        await loop._poll_and_merge_open_pr({})

        assert not any(c[:3] == ("gh", "pr", "review") for c in calls)
        assert any(c[:3] == ("gh", "pr", "merge") for c in calls)

    @pytest.mark.asyncio
    async def test_ci_failure_skips_review_and_merge(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, ...]] = []

        async def fake_run(*cmd: Any, **_: Any) -> str:
            calls.append(tuple(str(c) for c in cmd))
            if cmd[:3] == ("gh", "pr", "view"):
                return (
                    '{"state":"OPEN","reviewDecision":null,'
                    '"statusCheckRollup":[{"conclusion":"FAILURE"}]}'
                )
            return ""

        monkeypatch.setattr("repo_wiki_loop.run_subprocess", fake_run)

        loop = _stub_loop(
            _make_config(git_repo),
            credentials=Credentials(gh_token="ghs_test"),
        )
        loop._open_pr_url = "https://github.com/x/y/pull/13"

        stats: dict[str, Any] = {}
        await loop._poll_and_merge_open_pr(stats)

        assert stats["maintenance_pr_ci"] == "failure"
        # PR stays open for human triage.
        assert loop._open_pr_url == "https://github.com/x/y/pull/13"
        assert not any(c[:3] == ("gh", "pr", "review") for c in calls)
        assert not any(c[:3] == ("gh", "pr", "merge") for c in calls)


class TestTrackedActiveLintIntegration:
    """Phase 7: the heal's lint pass writes to the tracked layout, which
    becomes the diff ``_heal_and_open_maintenance_pr`` PRs. Post-#9539 the
    heal runs inside a worktree, so these tests drive the now-parameterized
    ``_lint_and_compile_repos`` directly against a tracked-layout root rather
    than the worktree.
    """

    @pytest.mark.asyncio
    async def test_flips_entry_status_when_source_issue_closed(
        self, git_repo: Path
    ) -> None:
        from datetime import UTC, datetime
        from unittest.mock import MagicMock

        from repo_wiki import RepoWikiStore

        tracked_root = git_repo / "repo_wiki"
        entry_path = (
            tracked_root / "acme" / "widget" / "patterns" / "0001-issue-42-x.md"
        )
        entry_path.parent.mkdir(parents=True)
        entry_path.write_text(
            "---\n"
            "id: 0001\n"
            "topic: patterns\n"
            "source_issue: 42\n"
            "source_phase: plan\n"
            f"created_at: {datetime.now(UTC).isoformat()}\n"
            "status: active\n"
            "---\n\n# Entry\n\nBody.\n",
            encoding="utf-8",
        )

        # MagicMock store isolates the legacy layout so only the tracked
        # lint (against ``tracked_root``) can flip the entry.
        store = MagicMock(spec=RepoWikiStore)
        store.active_lint.return_value = MagicMock(
            stale_entries=0,
            orphan_entries=0,
            total_entries=0,
            entries_marked_stale=0,
            orphans_pruned=0,
            empty_topics=[],
        )

        loop = _stub_loop(_make_config(git_repo))
        loop._wiki_compiler = None

        result = await loop._lint_and_compile_repos(
            ["acme/widget"], tracked_root, {42}, store=store
        )

        text = entry_path.read_text(encoding="utf-8")
        assert "status: stale" in text
        assert "stale_reason: source issue #42 closed" in text
        assert result["entries_marked_stale"] >= 1

    @pytest.mark.asyncio
    async def test_skips_tracked_lint_when_tracked_root_none(
        self, git_repo: Path
    ) -> None:
        from datetime import UTC, datetime
        from unittest.mock import MagicMock

        from repo_wiki import RepoWikiStore

        tracked_root = git_repo / "repo_wiki"
        entry_path = (
            tracked_root / "acme" / "widget" / "patterns" / "0001-issue-42-x.md"
        )
        entry_path.parent.mkdir(parents=True)
        entry_path.write_text(
            "---\n"
            "id: 0001\n"
            "topic: patterns\n"
            "source_issue: 42\n"
            "source_phase: plan\n"
            f"created_at: {datetime.now(UTC).isoformat()}\n"
            "status: active\n"
            "---\n\n# Entry\n",
            encoding="utf-8",
        )

        store = MagicMock(spec=RepoWikiStore)
        store.active_lint.return_value = MagicMock(
            stale_entries=0,
            orphan_entries=0,
            total_entries=0,
            entries_marked_stale=0,
            orphans_pruned=0,
            empty_topics=[],
        )

        loop = _stub_loop(_make_config(git_repo))
        loop._wiki_compiler = None

        # tracked_root=None mirrors the git-backed-disabled path.
        await loop._lint_and_compile_repos(["acme/widget"], None, {42}, store=store)

        # Tracked file untouched — lint only scans when tracked_root is set.
        assert "status: active" in entry_path.read_text(encoding="utf-8")


class TestTrackedCompileStatsReporting:
    """Regression for the ``total_compiled`` overcount: the heal must
    report the *post-synthesis* count returned by
    ``compile_topic_tracked`` rather than the pre-synthesis active
    count.  Using ``active_count`` would inflate ``entries_compiled``
    ~5-10× vs. the legacy ``compile_topic`` branch that aggregates
    into the same field.
    """

    @pytest.mark.asyncio
    async def test_adds_post_synthesis_count_not_active_count(
        self, git_repo: Path
    ) -> None:
        from datetime import UTC, datetime
        from unittest.mock import AsyncMock, MagicMock

        from repo_wiki import RepoWikiStore

        # 8 active entries in patterns, above the 5-entry threshold.
        tracked_root = git_repo / "repo_wiki"
        topic_dir = tracked_root / "acme" / "widget" / "patterns"
        topic_dir.mkdir(parents=True)
        for i in range(8):
            (topic_dir / f"000{i}-issue-{i}-x.md").write_text(
                "---\n"
                f"id: 000{i}\n"
                "topic: patterns\n"
                f"source_issue: {i}\n"
                "source_phase: plan\n"
                f"created_at: {datetime.now(UTC).isoformat()}\n"
                "status: active\n"
                "---\n\n# Entry\n",
                encoding="utf-8",
            )

        store = MagicMock(spec=RepoWikiStore)
        store.active_lint.return_value = MagicMock(
            stale_entries=0,
            orphan_entries=0,
            total_entries=0,
            entries_marked_stale=0,
            orphans_pruned=0,
            empty_topics=[],
        )

        compiler = MagicMock()
        compiler.compile_topic_tracked = AsyncMock(return_value=2)

        loop = _stub_loop(_make_config(git_repo))
        loop._wiki_compiler = compiler

        result = await loop._lint_and_compile_repos(
            ["acme/widget"], tracked_root, set(), store=store
        )

        # Must be 2 (post-synthesis), not 8 (active_count pre-fix).
        assert result["entries_compiled"] == 2
        # Defence-in-depth: if the 5-entry threshold is ever raised above
        # our 8-entry fixture, the outer assertion would still pass with
        # entries_compiled == 0 (0 != 2 → fail, but for the wrong reason).
        # Pinning await_count guarantees the compiler was actually invoked.
        compiler.compile_topic_tracked.assert_awaited_once()


def _git(cwd: Path, *args: str) -> str:
    """Run a real git command in ``cwd`` and return stripped stdout."""
    proc = subprocess.run(
        ["git", *args], check=False, cwd=cwd, capture_output=True, text=True, timeout=60
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout.strip()


class TestHealLeavesRepoRootClean:
    """#9539 load-bearing invariant: the heal+PR runs entirely inside an
    ephemeral worktree off ``origin/<base>``. ``repo_root`` is never mutated,
    so the factory's checkout stays clean — and the healed content lands on
    the pushed maintenance branch, not the host checkout.
    """

    @pytest.mark.asyncio
    async def test_heal_leaves_repo_root_clean_and_pushes_healed_content(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from datetime import UTC, datetime

        # --- bare remote + local checkout with a stale-able tracked entry ---
        remote = tmp_path / "remote.git"
        subprocess.run(["git", "init", "--bare", str(remote)], check=True)

        local = tmp_path / "local"
        subprocess.run(["git", "clone", str(remote), str(local)], check=True)
        _git(local, "checkout", "-b", "main")
        _git(local, "config", "user.email", "t@t")
        _git(local, "config", "user.name", "t")

        entry_rel = "repo_wiki/acme/widget/patterns/0001-issue-42-x.md"
        entry_path = local / entry_rel
        entry_path.parent.mkdir(parents=True)
        entry_path.write_text(
            "---\n"
            "id: 0001\n"
            "topic: patterns\n"
            "source_issue: 42\n"
            "source_phase: plan\n"
            f"created_at: {datetime.now(UTC).isoformat()}\n"
            "status: active\n"
            "---\n\n# Entry\n\nBody.\n",
            encoding="utf-8",
        )
        (local / "repo_wiki" / "acme" / "widget" / "index.md").write_text(
            "# index\n", encoding="utf-8"
        )
        # A committed legacy docs/wiki dir so the worktree's legacy store is
        # distinct from the tracked layout (matches the factory checkout).
        (local / "docs" / "wiki").mkdir(parents=True)
        (local / "docs" / "wiki" / ".keep").write_text("", encoding="utf-8")
        _git(local, "add", "-A")
        _git(local, "commit", "-m", "seed wiki")
        # Push both base candidates so config.base_branch() resolves either way.
        _git(local, "push", "-u", "origin", "main")
        _git(local, "checkout", "-b", "staging")
        _git(local, "push", "-u", "origin", "staging")
        _git(local, "checkout", "main")

        # --- stub run_subprocess: real git passthrough, gh stubbed ---
        async def fake_run(
            *cmd: str,
            cwd: Any = None,
            gh_token: str = "",
            timeout: float = 120.0,
            runner: Any = None,
        ) -> str:
            del gh_token, timeout, runner
            if cmd[:2] == ("gh", "pr") and cmd[2] == "create":
                return "https://github.com/acme/widget/pull/123\n"
            if cmd[:2] == ("gh", "pr"):
                return ""
            proc = subprocess.run(
                list(cmd),
                check=False,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"{cmd}: {proc.stderr}")
            return proc.stdout.strip()

        monkeypatch.setattr("subprocess_util.run_subprocess", fake_run)

        config = _make_config(local)
        loop = _stub_loop(config, credentials=Credentials(gh_token="ghs_test"))
        loop._wiki_compiler = None

        stats: dict[str, Any] = {"queue_drained": 0}
        await loop._heal_and_open_maintenance_pr({42}, stats)

        # KEY INVARIANT: repo_root's working tree is untouched.
        assert _git(local, "status", "--porcelain") == ""
        # The host entry is still ACTIVE — the heal happened in the worktree.
        assert "status: active" in entry_path.read_text(encoding="utf-8")
        # The PR was tracked and the worktree cleaned up.
        assert loop._open_pr_url == "https://github.com/acme/widget/pull/123"
        assert stats["maintenance_pr"] == "https://github.com/acme/widget/pull/123"
        assert not list(tmp_path.glob("genpr-*"))

        # The healed (stale-flipped) content was pushed to the maintenance
        # branch on the remote, NOT left in repo_root.
        branch = loop._open_pr_branch
        assert branch is not None
        pushed = _git(remote, "show", f"{branch}:{entry_rel}")
        assert "status: stale" in pushed
        assert "stale_reason: source issue #42 closed" in pushed
