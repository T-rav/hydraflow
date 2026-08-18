"""MockWorld scenario for ErosionMetricsLoop (#10107, epic #10104).

End-to-end over FakeGitHub + a real (tiny) git repo fixture on disk — the
erosion sensors' git adapters (``changed_files_for_range`` /
``added_symbols_for_range``) shell out to real git against
``config.repo_root``, so this scenario builds an actual repo rather than
seeding FakeGitHub state (mirrors ``tests/test_erosion_metrics_loop.py``'s
fixture, one layer up: this test proves the loop + FakeGitHub port
integrate correctly, not just the loop's internal logic in isolation).

* ``test_seeded_erosive_commit_range_files_one_issue`` — a commit range
  that scatters a newly-added symbol across 3 modules gets exactly one
  ``hydraflow-find`` issue filed via the real ``FakeGitHub.create_issue``
  path.
* ``test_re_tick_does_not_refile`` — a second tick with no new commits
  (dedup by SHA cursor) files nothing further.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "erosion_repo"
    repo.mkdir()
    (repo / "src").mkdir()
    _git(repo, "init", "-q")
    _git(repo, "commit", "-q", "-m", "init", "--allow-empty")
    return repo


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _seed_scattered_symbol(repo: Path) -> tuple[str, str]:
    """Base commit (3 plain modules) + erosive commit (shared symbol scattered)."""
    for pkg in ("moda", "modb", "modc"):
        (repo / "src" / pkg).mkdir(parents=True)
        (repo / "src" / pkg / "m.py").write_text("x = 1\n")
    base_sha = _commit_all(repo, "base modules")

    for pkg in ("moda", "modb", "modc"):
        path = repo / "src" / pkg / "m.py"
        path.write_text(path.read_text() + "\n\ndef shared_helper():\n    pass\n")
    erosive_sha = _commit_all(repo, "scatter shared_helper across 3 modules")

    return base_sha, erosive_sha


def _make_state(initial_sha: str) -> Any:
    from unittest.mock import MagicMock

    state = MagicMock()
    cursor = {"sha": initial_sha}
    state.get_erosion_last_processed_sha.side_effect = lambda: cursor["sha"]

    def _set(sha: str) -> None:
        cursor["sha"] = sha

    state.set_erosion_last_processed_sha.side_effect = _set
    state._cursor = cursor
    return state


def _make_dedup() -> Any:
    from unittest.mock import MagicMock

    dedup = MagicMock()
    store: set[str] = set()
    dedup.get.side_effect = lambda: set(store)

    def _set_all(values: set[str]) -> None:
        store.clear()
        store.update(values)

    dedup.set_all.side_effect = _set_all
    return dedup


def _build_loop(tmp_path: Path, repo: Path, github: Any, state: Any) -> Any:
    from erosion_metrics_loop import ErosionMetricsLoop
    from tests.helpers import make_bg_loop_deps

    bg = make_bg_loop_deps(tmp_path)
    object.__setattr__(bg.config, "repo_root", repo)
    object.__setattr__(bg.config, "erosion_metrics_loop_enabled", True)
    return ErosionMetricsLoop(
        config=bg.config,
        pr_manager=github,
        state=state,
        dedup=_make_dedup(),
        deps=bg.loop_deps,
    )


class TestErosionMetricsScenario:
    async def test_seeded_erosive_commit_range_files_one_issue(
        self, tmp_path: Path
    ) -> None:
        world = MockWorld(tmp_path)
        github = world.github
        repo = _init_repo(tmp_path)
        base_sha, erosive_sha = _seed_scattered_symbol(repo)

        state = _make_state(base_sha)
        loop = _build_loop(tmp_path, repo, github, state)

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["filed"] == 1
        assert len(github._issues) == 1
        (issue,) = github._issues.values()
        assert "shared_helper" in issue.title
        assert "hydraflow-find" in issue.labels
        assert state._cursor["sha"] == erosive_sha

    async def test_re_tick_does_not_refile(self, tmp_path: Path) -> None:
        world = MockWorld(tmp_path)
        github = world.github
        repo = _init_repo(tmp_path)
        base_sha, _erosive_sha = _seed_scattered_symbol(repo)

        state = _make_state(base_sha)
        loop = _build_loop(tmp_path, repo, github, state)

        first = await loop._do_work()
        assert first["filed"] == 1

        second = await loop._do_work()

        assert second["status"] == "no_new_commits"
        assert len(github._issues) == 1  # unchanged — not refiled

    async def test_catalog_default_dedup_prevents_refiling_on_cursor_reset(
        self, tmp_path: Path
    ) -> None:
        """Regression guard for #11446.

        Builds the loop through ``LoopCatalog`` without seeding
        ``erosion_metrics_dedup``, so the catalog's own default dedup port
        is exercised (not this file's hand-rolled stateful ``_make_dedup``
        fake). A cursor reset (restart / state loss) makes the loop re-scan
        the same erosive commit range on the second tick; dedup — not the
        SHA cursor — is what must prevent the duplicate filing.
        """
        from tests.helpers import make_bg_loop_deps
        from tests.scenarios.catalog import LoopCatalog
        from tests.scenarios.catalog.loop_registrations import ensure_registered

        ensure_registered()

        world = MockWorld(tmp_path)
        github = world.github
        repo = _init_repo(tmp_path)
        base_sha, _erosive_sha = _seed_scattered_symbol(repo)

        state = _make_state(base_sha)

        bg = make_bg_loop_deps(tmp_path)
        object.__setattr__(bg.config, "repo_root", repo)
        object.__setattr__(bg.config, "erosion_metrics_loop_enabled", True)

        ports: dict = {"github": github, "erosion_metrics_state": state}
        loop = LoopCatalog.instantiate(
            "erosion_metrics", ports=ports, config=bg.config, deps=bg.loop_deps
        )

        first = await loop._do_work()
        assert first["filed"] == 1
        assert len(github._issues) == 1

        state._cursor["sha"] = base_sha  # simulate a cursor reset

        second = await loop._do_work()

        assert second["filed"] == 0
        assert len(github._issues) == 1  # dedup — not refiled
