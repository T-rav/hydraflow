"""MockWorld scenario for `MemoryBacklogLoop` (ADR-0089).

Tier-3 expansion: the existing builder lives in
``tests/scenarios/catalog/loop_registrations.py`` but no scenario test
exercises the loop end-to-end. Per ``docs/standards/testing/README.md``, a
loop-observable bug fix (YAML-resilience #?) requires a scenario layer
alongside the unit regression.

Pattern B (direct instantiation): the loop wants fine-grained config
control (``memory_backlog_label`` / ``find_label`` shaping) and the mirror
dir is colocated with a real tmp git repo so ``_commit_mirror_updates``
doesn't warn on every tick.
"""

from __future__ import annotations

import asyncio
import subprocess as _sp
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.scenario_loops


def _make_repo_with_mirror(tmp_path: Path) -> Path:
    """Init a throwaway git repo and return the repo root.

    ``MemoryBacklogLoop._commit_mirror_updates`` shells out to ``git add`` /
    ``git commit``. A real repo lets those calls succeed silently; otherwise
    the loop logs a WARN per tick, which is fine but noisy in tests.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _sp.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _sp.run(
        ["git", "-C", str(repo), "config", "user.email", "t@example.com"],
        check=True,
        capture_output=True,
    )
    _sp.run(
        ["git", "-C", str(repo), "config", "user.name", "Tester"],
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("init\n")
    _sp.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    _sp.run(
        ["git", "-C", str(repo), "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )
    (repo / "docs" / "wiki" / "memory-feedback").mkdir(parents=True)
    return repo


def _write_entry(
    mirror_dir: Path, slug: str, *, status: str = "pending", body: str = "rule body"
) -> Path:
    """Write a well-formed mirror entry."""
    path = mirror_dir / f"{slug}.md"
    path.write_text(
        "---\n"
        f"source: {slug}.md\n"
        f"name: {slug}\n"
        f"description: plain description for {slug}\n"
        f"status: {status}\n"
        "---\n\n"
        f"{body}\n"
    )
    return path


def _make_loop(repo_root: Path):
    """Build a MemoryBacklogLoop with a real config + FakeGitHub PRManager."""
    from base_background_loop import LoopDeps  # noqa: PLC0415
    from dedup_store import DedupStore  # noqa: PLC0415
    from events import EventBus  # noqa: PLC0415
    from memory_backlog_loop import MemoryBacklogLoop  # noqa: PLC0415
    from mockworld.fakes.fake_github import FakeGitHub  # noqa: PLC0415
    from tests.helpers import ConfigFactory  # noqa: PLC0415

    config = ConfigFactory.create(repo_root=repo_root)
    bus = EventBus()
    stop = asyncio.Event()
    stop.set()
    deps = LoopDeps(
        event_bus=bus,
        stop_event=stop,
        status_cb=MagicMock(),
        enabled_cb=lambda _: True,
        sleep_fn=AsyncMock(),
    )

    state = MagicMock()
    state.get_memory_backlog_attempts.return_value = 0
    state.inc_memory_backlog_attempts.return_value = 1

    dedup_path = config.data_root / "dedup" / "memory_backlog.json"
    dedup_path.parent.mkdir(parents=True, exist_ok=True)
    dedup = DedupStore("memory_backlog", dedup_path)

    github = FakeGitHub()

    loop = MemoryBacklogLoop(
        config=config, state=state, pr_manager=github, dedup=dedup, deps=deps
    )
    return loop, github


class TestMemoryBacklogScenario:
    async def test_pending_entry_files_issue(self, tmp_path: Path) -> None:
        """Happy path: a single pending entry yields one create_issue call."""
        repo = _make_repo_with_mirror(tmp_path)
        _write_entry(repo / "docs" / "wiki" / "memory-feedback", "feedback-alpha")
        loop, github = _make_loop(repo)

        result = await loop._do_work()

        assert result == {
            "status": "ok",
            "filed": 1,
            "skipped": 0,
            "escalated": 0,
            "summarized": 0,
        }
        assert len(github._issues) == 1
        issue = next(iter(github._issues.values()))
        assert "feedback-alpha" in issue.title

    async def test_malformed_yaml_does_not_crash_loop(self, tmp_path: Path) -> None:
        """A malformed mirror entry must not crash the loop — the good entries
        are still filed. Regression for the YAML-resilience bug observed in
        ``server.log`` 2026-05-13 (loop logged "iteration failed — will retry
        next cycle" indefinitely until a manual fix)."""
        repo = _make_repo_with_mirror(tmp_path)
        mirror = repo / "docs" / "wiki" / "memory-feedback"
        _write_entry(mirror, "feedback-good")
        # Backtick-leading value is a YAML 1.1 reserved indicator — same shape
        # as the original on-disk corruption in feedback-make-quality-pipe-exit-code.md.
        (mirror / "feedback-bad.md").write_text(
            "---\n"
            "source: feedback-bad.md\n"
            "name: bad\n"
            "description: `backtick-leading` is a YAML reserved indicator\n"
            "status: pending\n"
            "---\n\nbody\n"
        )
        loop, github = _make_loop(repo)

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["filed"] == 1
        assert len(github._issues) == 1


class TestARecloneDoesNotReFile:
    """#11963 — the guard has to survive losing the local frontmatter.

    Unit tests see the loop's decision against a mocked board. Only this layer
    replays the sequence that actually happened: file an issue, lose the
    write-back (the commit went into a workspace nothing pushes), come back on
    a checkout that still reads `pending`, and tick again.

    `FakeGitHub` is the board here, not a mock — the second tick has to find the
    first tick's own issue through the same port a live run would.
    """

    async def test_a_second_tick_on_a_reset_checkout_files_nothing(
        self, tmp_path: Path
    ) -> None:
        repo = _make_repo_with_mirror(tmp_path)
        mirror = repo / "docs" / "wiki" / "memory-feedback"
        _write_entry(mirror, "feedback-alpha")
        loop, github = _make_loop(repo)

        first = await loop._do_work()
        assert first["filed"] == 1

        # The re-clone: frontmatter back to `pending`, dedup gone. The issue
        # the first tick filed is still open on the board.
        _write_entry(mirror, "feedback-alpha", status="pending")
        loop._dedup.set_all(set())

        second = await loop._do_work()

        assert second["filed"] == 0

    async def test_the_reset_checkout_heals_its_own_frontmatter(
        self, tmp_path: Path
    ) -> None:
        repo = _make_repo_with_mirror(tmp_path)
        mirror = repo / "docs" / "wiki" / "memory-feedback"
        path = _write_entry(mirror, "feedback-alpha")
        loop, github = _make_loop(repo)

        await loop._do_work()
        _write_entry(mirror, "feedback-alpha", status="pending")
        loop._dedup.set_all(set())

        await loop._do_work()

        assert "status: issue-open" in path.read_text()

    async def test_only_one_issue_exists_on_the_board_afterwards(
        self, tmp_path: Path
    ) -> None:
        # The symptom a human would have seen: a duplicate of an issue that was
        # never closed.
        repo = _make_repo_with_mirror(tmp_path)
        mirror = repo / "docs" / "wiki" / "memory-feedback"
        _write_entry(mirror, "feedback-alpha")
        loop, github = _make_loop(repo)

        await loop._do_work()
        _write_entry(mirror, "feedback-alpha", status="pending")
        loop._dedup.set_all(set())
        await loop._do_work()

        issues = await github.list_issues_by_label("hydraflow-memory-backlog")
        assert len(issues) == 1

    async def test_a_genuinely_new_entry_still_files(self, tmp_path: Path) -> None:
        # The decoy: a guard that skipped everything after the first tick would
        # pass all three tests above and file nothing again, ever.
        repo = _make_repo_with_mirror(tmp_path)
        mirror = repo / "docs" / "wiki" / "memory-feedback"
        _write_entry(mirror, "feedback-alpha")
        loop, github = _make_loop(repo)

        await loop._do_work()
        _write_entry(mirror, "feedback-beta")

        second = await loop._do_work()

        assert second["filed"] == 1
