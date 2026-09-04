"""One read path, committed file preferred over the cache (ADR-0149)."""

import pytest

from change_chain import archive_root, chain_dir
from change_chain_reader import read_plan
from tests.helpers import ConfigFactory


@pytest.fixture
def config():
    return ConfigFactory.create()


def _cache(config, issue: int, body: str) -> None:
    config.plans_dir.mkdir(parents=True, exist_ok=True)
    (config.plans_dir / f"issue-{issue}.md").write_text(body)


def _committed(root, issue: int, body: str) -> None:
    directory = chain_dir(root, issue)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "plan.md").write_text(body)


def test_prefers_the_committed_file_when_present(config, tmp_path):
    _committed(tmp_path, 7, "committed")
    _cache(config, 7, "cached")

    assert read_plan(config, 7, worktree=tmp_path) == "committed"


def test_falls_back_to_the_cache_when_the_branch_has_no_chain(config, tmp_path):
    _cache(config, 7, "cached")

    assert read_plan(config, 7, worktree=tmp_path) == "cached"


def test_returns_empty_string_when_neither_exists(config, tmp_path):
    assert read_plan(config, 7, worktree=tmp_path) == ""


def test_reads_an_archived_plan_after_compaction(config, tmp_path):
    archived = archive_root(tmp_path) / "2026-Q3" / "issue-7"
    archived.mkdir(parents=True)
    (archived / "plan.md").write_text("archived")

    assert read_plan(config, 7, worktree=tmp_path) == "archived"


def test_an_archived_plan_still_beats_the_cache(config, tmp_path):
    archived = archive_root(tmp_path) / "2026-Q3" / "issue-7"
    archived.mkdir(parents=True)
    (archived / "plan.md").write_text("archived")
    _cache(config, 7, "cached")

    assert read_plan(config, 7, worktree=tmp_path) == "archived"


def test_searches_the_repo_root_when_no_worktree_is_given(config):
    _committed(config.repo_root, 7, "committed in the primary repo")

    assert read_plan(config, 7) == "committed in the primary repo"


def test_a_chain_directory_without_a_plan_falls_back_to_the_cache(config, tmp_path):
    chain_dir(tmp_path, 7).mkdir(parents=True)
    _cache(config, 7, "cached")

    assert read_plan(config, 7, worktree=tmp_path) == "cached"


def test_another_issues_plan_is_not_returned(config, tmp_path):
    _committed(tmp_path, 8, "issue eight's plan")

    assert read_plan(config, 7, worktree=tmp_path) == ""
