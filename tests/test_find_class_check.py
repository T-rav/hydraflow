"""Unit tests for the ``scripts/find_class_check.py`` CLI shell (#11292).

Shims ``subprocess.run`` (the seam the script calls ``gh`` through) rather
than spawning a real ``gh`` process. Covers the fold/file-new outcomes and
the load-bearing distinction from the design: a ``gh`` failure must surface
as exit code ``2``, never silently fall back to ``FILE-NEW`` (which would
let a transient auth/network blip file an avoidable duplicate issue).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from find_class_key import compute_class_key, render_marker  # noqa: E402

_SHELL_PATH = Path(__file__).resolve().parent.parent / "scripts" / "find_class_check.py"


def _load_shell():
    spec = importlib.util.spec_from_file_location("find_class_check_shell", _SHELL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cli = _load_shell()


def _completed(
    returncode: int, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["gh"], returncode=returncode, stdout=stdout, stderr=stderr
    )


class TestResolveRepo:
    def test_explicit_repo_short_circuits(self) -> None:
        assert cli._resolve_repo("owner/repo") == "owner/repo"

    def test_falls_back_to_git_remote(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_run(cmd, **_kwargs):
            assert cmd[:3] == ["git", "-C", str(cli.REPO_ROOT)]
            return _completed(0, stdout="https://github.com/T-rav/hydraflow.git\n")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        assert cli._resolve_repo(None) == "T-rav/hydraflow"

    def test_git_remote_failure_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            subprocess, "run", lambda *_a, **_kw: _completed(1, stderr="not a repo")
        )
        with pytest.raises(cli.GhCommandError):
            cli._resolve_repo(None)


class TestListOpenIssues:
    def test_parses_gh_json_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = [{"number": 11188, "title": "x", "body": "y"}]
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *_a, **_kw: _completed(0, stdout=json.dumps(payload)),
        )
        assert cli.list_open_issues("owner/repo", "hydraflow-find") == payload

    def test_gh_failure_raises_gh_command_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            subprocess, "run", lambda *_a, **_kw: _completed(1, stderr="rate limited")
        )
        with pytest.raises(cli.GhCommandError):
            cli.list_open_issues("owner/repo", "hydraflow-find")

    def test_invalid_json_raises_gh_command_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            subprocess, "run", lambda *_a, **_kw: _completed(0, stdout="not json")
        )
        with pytest.raises(cli.GhCommandError):
            cli.list_open_issues("owner/repo", "hydraflow-find")


class TestRunCheck:
    def test_matching_class_issue_returns_fold(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        key = compute_class_key("branch-parser", "branch namespace missing")
        monkeypatch.setattr(
            cli,
            "list_open_issues",
            lambda *_a, **_kw: [
                {"number": 11188, "title": "x", "body": render_marker(key)}
            ],
        )
        code, message = cli.run_check(
            source="branch-parser",
            needle="branch namespace missing",
            title="sibling site",
            repo="owner/repo",
            label="hydraflow-find",
        )
        assert (code, message) == (0, "FOLD 11188")

    def test_no_match_returns_file_new(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cli, "list_open_issues", lambda *_a, **_kw: [])
        code, message = cli.run_check(
            source="branch-parser",
            needle="branch namespace missing",
            title="site",
            repo="owner/repo",
            label="hydraflow-find",
        )
        assert (code, message) == (1, "FILE-NEW")


class TestMain:
    def test_emit_marker_prints_marker_and_exits_zero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = cli.main(
            ["--emit-marker", "--source", "branch-parser", "--needle", "gap"]
        )
        assert exit_code == 0
        expected = render_marker(compute_class_key("branch-parser", "gap"))
        assert capsys.readouterr().out.strip() == expected

    def test_check_fold_prints_fold_and_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(cli, "_resolve_repo", lambda _explicit: "owner/repo")
        monkeypatch.setattr(cli, "run_check", lambda **_kw: (0, "FOLD 42"))
        exit_code = cli.main(
            [
                "--check",
                "--source",
                "branch-parser",
                "--needle",
                "gap",
                "--title",
                "site title",
            ]
        )
        assert exit_code == 0
        assert capsys.readouterr().out.strip() == "FOLD 42"

    def test_check_file_new_exits_one(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(cli, "_resolve_repo", lambda _explicit: "owner/repo")
        monkeypatch.setattr(cli, "run_check", lambda **_kw: (1, "FILE-NEW"))
        exit_code = cli.main(
            [
                "--check",
                "--source",
                "branch-parser",
                "--needle",
                "gap",
                "--title",
                "site title",
            ]
        )
        assert exit_code == 1
        assert capsys.readouterr().out.strip() == "FILE-NEW"

    def test_gh_failure_exits_two_never_file_new(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def _raise(*_a, **_kw):
            raise cli.GhCommandError("gh issue list failed: rate limited")

        monkeypatch.setattr(cli, "_resolve_repo", lambda _explicit: "owner/repo")
        monkeypatch.setattr(cli, "run_check", _raise)
        exit_code = cli.main(
            [
                "--check",
                "--source",
                "branch-parser",
                "--needle",
                "gap",
                "--title",
                "site title",
            ]
        )
        assert exit_code == 2
        out = capsys.readouterr()
        assert "FILE-NEW" not in out.out
        assert "rate limited" in out.err

    def test_check_and_emit_marker_together_is_usage_error(self) -> None:
        with pytest.raises(SystemExit):
            cli.main(
                [
                    "--check",
                    "--emit-marker",
                    "--source",
                    "branch-parser",
                    "--needle",
                    "gap",
                ]
            )

    def test_check_without_title_is_usage_error(self) -> None:
        with pytest.raises(SystemExit):
            cli.main(["--check", "--source", "branch-parser", "--needle", "gap"])
