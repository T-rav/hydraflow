"""Tests for git_revision — boot SHA + commits-behind staleness helpers."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import git_revision


@pytest.fixture(autouse=True)
def _reset_boot_sha_cache():
    """Each test starts with an uncaptured boot SHA."""
    git_revision._BOOT_SHA_SLOT[0] = git_revision._UNSET
    yield
    git_revision._BOOT_SHA_SLOT[0] = git_revision._UNSET


def _fake_run(mapping):
    """Return a subprocess.run stub keyed on the git subcommand."""

    def _run(cmd, *_args, **_kwargs):
        key = cmd[1]  # cmd == ["git", <subcommand>, ...]
        rc, out = mapping[key]
        return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr="")

    return _run


class TestBootSha:
    def test_returns_head_sha(self, monkeypatch) -> None:
        monkeypatch.setattr(
            git_revision.subprocess,
            "run",
            _fake_run({"rev-parse": (0, "abc123\n")}),
        )
        assert git_revision.get_boot_sha() == "abc123"

    def test_captured_once_and_not_reread(self, monkeypatch) -> None:
        # First read captures "abc123"; HEAD then advances (git pull, no
        # restart) but the cached boot SHA must NOT change.
        monkeypatch.setattr(
            git_revision.subprocess,
            "run",
            _fake_run({"rev-parse": (0, "abc123\n")}),
        )
        assert git_revision.get_boot_sha() == "abc123"

        monkeypatch.setattr(
            git_revision.subprocess,
            "run",
            _fake_run({"rev-parse": (0, "def456\n")}),
        )
        assert git_revision.get_boot_sha() == "abc123"

    def test_returns_none_on_nonzero_exit(self, monkeypatch) -> None:
        monkeypatch.setattr(
            git_revision.subprocess,
            "run",
            _fake_run({"rev-parse": (128, "")}),
        )
        assert git_revision.get_boot_sha() is None

    def test_returns_none_when_git_missing(self, monkeypatch) -> None:
        def _boom(*_a, **_k):
            raise FileNotFoundError("git not found")

        monkeypatch.setattr(git_revision.subprocess, "run", _boom)
        assert git_revision.get_boot_sha() is None

    def test_returns_none_on_timeout(self, monkeypatch) -> None:
        def _boom(*_a, **_k):
            raise subprocess.TimeoutExpired(cmd="git", timeout=5)

        monkeypatch.setattr(git_revision.subprocess, "run", _boom)
        assert git_revision.get_boot_sha() is None


class TestCommitsBehind:
    def test_counts_commits_behind_base_ref(self, monkeypatch) -> None:
        monkeypatch.setattr(
            git_revision.subprocess,
            "run",
            _fake_run({"rev-parse": (0, "abc123\n"), "rev-list": (0, "7\n")}),
        )
        assert git_revision.get_commits_behind() == 7

    def test_zero_when_up_to_date(self, monkeypatch) -> None:
        monkeypatch.setattr(
            git_revision.subprocess,
            "run",
            _fake_run({"rev-parse": (0, "abc123\n"), "rev-list": (0, "0\n")}),
        )
        assert git_revision.get_commits_behind() == 0

    def test_none_when_boot_sha_unavailable(self, monkeypatch) -> None:
        monkeypatch.setattr(
            git_revision.subprocess,
            "run",
            _fake_run({"rev-parse": (128, "")}),
        )
        assert git_revision.get_commits_behind() is None

    def test_none_on_rev_list_failure(self, monkeypatch) -> None:
        monkeypatch.setattr(
            git_revision.subprocess,
            "run",
            _fake_run({"rev-parse": (0, "abc123\n"), "rev-list": (128, "")}),
        )
        assert git_revision.get_commits_behind() is None

    def test_none_on_unparseable_count(self, monkeypatch) -> None:
        monkeypatch.setattr(
            git_revision.subprocess,
            "run",
            _fake_run(
                {"rev-parse": (0, "abc123\n"), "rev-list": (0, "not-a-number\n")}
            ),
        )
        assert git_revision.get_commits_behind() is None

    def test_none_on_timeout(self, monkeypatch) -> None:
        def _run(cmd, *_a, **_k):
            if cmd[1] == "rev-parse":
                return subprocess.CompletedProcess(cmd, 0, stdout="abc123\n", stderr="")
            raise subprocess.TimeoutExpired(cmd="git", timeout=5)

        monkeypatch.setattr(git_revision.subprocess, "run", _run)
        assert git_revision.get_commits_behind() is None
