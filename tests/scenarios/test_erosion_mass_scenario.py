"""MockWorld scenario for ErosionMetricsLoop's mass + suite-hygiene class issues.

End-to-end over FakeGitHub + a real (tiny) git repo on disk, one layer up
from ``tests/test_erosion_metrics_loop_mass.py``: proves the loop's
three-way class-issue dedup drives the REAL ``FakeGitHub`` port —
``create_issue`` → ``get_issue_state`` → ``update_issue_body`` → ``close_issue``
→ re-file — not a MagicMock.

* seeded god class + parametrize group → exactly two ``hydraflow-find`` class
  issues, each carrying the class marker;
* same reading, new commit → nothing new (open + same roster);
* class grows, new commit → body refreshed in place, still two issues;
* mass issue closed by a human, new commit → re-filed once (three issues total).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from find_class_key import extract_class_key
from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _head(repo: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "mass_repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    _git(repo, "init", "-q")
    _git(repo, "commit", "-q", "-m", "init", "--allow-empty")
    return repo


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _head(repo)


def _god_class(methods: int) -> str:
    lines = ["class Hub:"]
    for i in range(methods):
        lines.extend([f"    def m{i}(self):", "        return 1"])
    return "\n".join(lines) + "\n"


def _seed(repo: Path) -> str:
    (repo / "src" / "hub.py").write_text(_god_class(40))
    (repo / "tests" / "test_dup.py").write_text(
        "".join(
            f"def test_case_{i}():\n    assert f('{i}') == {i}\n\n" for i in range(3)
        )
    )
    return _commit_all(repo, "seed god class + parametrize group")


def _make_state(initial_sha: str) -> Any:
    from unittest.mock import MagicMock

    state = MagicMock()
    cursor = {"sha": initial_sha}
    state.get_erosion_last_processed_sha.side_effect = lambda: cursor["sha"]
    state.set_erosion_last_processed_sha.side_effect = lambda sha: cursor.update(
        sha=sha
    )
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


class TestErosionMassScenario:
    async def test_class_issues_file_refresh_and_refile_through_fake_github(
        self, tmp_path: Path
    ) -> None:
        world = MockWorld(tmp_path)
        github = world.github
        repo = _init_repo(tmp_path)
        base_sha = _head(repo)
        _seed(repo)
        loop = _build_loop(tmp_path, repo, github, _make_state(base_sha))

        # Tick 1: one class issue per kind, both carrying the class marker.
        first = await loop._do_work()
        assert first["status"] == "ok"
        assert first["filed"] == 2
        assert len(github._issues) == 2
        by_title = {issue.title: issue for issue in github._issues.values()}
        mass_title = next(t for t in by_title if "god class" in t)
        suite_title = next(t for t in by_title if "parametrize" in t)
        for issue in by_title.values():
            assert "hydraflow-find" in issue.labels
            assert extract_class_key(issue.body).startswith(
                "findclass:erosion_metrics:"
            )
        mass_number = by_title[mass_title].number

        # Tick 2: unrelated commit, same reading → open + same roster → nothing.
        (repo / "src" / "other.py").write_text("x = 1\n")
        _commit_all(repo, "unrelated")
        second = await loop._do_work()
        assert second["filed"] == 0 and second["refreshed"] == 0
        assert len(github._issues) == 2

        # Tick 3: the god class grows → roster changes → body refreshed in place.
        (repo / "src" / "hub.py").write_text(_god_class(45))
        _commit_all(repo, "hub grows")
        third = await loop._do_work()
        assert third["filed"] == 0 and third["refreshed"] == 1
        assert len(github._issues) == 2
        assert "45 methods" in github._issues[mass_number].body

        # Tick 4: a human closes the mass issue without fixing it → re-filed once.
        await github.close_issue(mass_number)
        (repo / "src" / "yet_another.py").write_text("y = 2\n")
        _commit_all(repo, "another unrelated")
        fourth = await loop._do_work()
        assert fourth["filed"] == 1
        assert len(github._issues) == 3
        open_mass = [
            i
            for i in github._issues.values()
            if "god class" in i.title and i.state == "open"
        ]
        assert len(open_mass) == 1 and open_mass[0].number != mass_number
        assert suite_title in {i.title for i in github._issues.values()}
