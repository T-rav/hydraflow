"""Regression #12062: auto_pr commits stale generated arch artifacts.

TermProposerLoop's first post-v1.0.1 cycle failed at commit time: its staged
term file is an INPUT to docs/arch/generated/, `open_automated_pr` never
regenerated, and the worktree pre-commit hook rejected the commit ("docs/
arch/generated/ is out of sync — Run: make arch-regen-stage"). Every
`auto_pr` caller whose files touch arch inputs failed the same way.

Pins: the regen step runs in the WORKTREE between staging and commit; what
it stages rides the same commit; and a failing regen is fail-open (the flow
proceeds rather than erroring earlier than the hook would).
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

import auto_pr
from auto_pr import open_automated_pr


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True)
    return remote


@pytest.fixture
def local_repo(tmp_path: Path, bare_remote: Path) -> Path:
    local = tmp_path / "local"
    subprocess.run(["git", "clone", str(bare_remote), str(local)], check=True)
    subprocess.run(["git", "-C", str(local), "checkout", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(local), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(local), "config", "user.name", "t"], check=True)
    (local / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(local), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(local), "commit", "-m", "seed"], check=True)
    subprocess.run(["git", "-C", str(local), "push", "origin", "main"], check=True)
    return local


def _fake_gh(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        cmd, 0, stdout="https://github.com/x/y/pull/1\n", stderr=""
    )


def _write_recording_regen(tmp_path: Path) -> tuple[Path, Path]:
    """A stand-in regen tool: records its cwd, writes + stages an artifact —
    the observable shape of `make arch-regen-stage`."""
    record = tmp_path / "regen-cwd.txt"
    script = tmp_path / "fake-regen.sh"
    script.write_text(
        "#!/bin/sh\n"
        f'pwd > "{record}"\n'
        'mkdir -p docs/arch/generated\n'
        'echo regenerated > docs/arch/generated/artifact.md\n'
        "git add docs/arch/generated/artifact.md\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script, record


def test_regen_runs_in_worktree_and_its_output_rides_the_commit(
    local_repo: Path, bare_remote: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script, record = _write_recording_regen(tmp_path)
    monkeypatch.setattr(auto_pr, "_ARCH_REGEN_ARGV", (str(script),))
    monkeypatch.setattr(auto_pr, "_run_gh", _fake_gh)
    (local_repo / "docs" / "wiki" / "terms").mkdir(parents=True)
    term = local_repo / "docs" / "wiki" / "terms" / "widget.md"
    term.write_text("# widget\n", encoding="utf-8")

    result = open_automated_pr(
        repo_root=local_repo,
        branch="ul/widget",
        files=[term],
        title="feat(ul): widget",
        body="",
        base="main",
        auto_merge=False,
        worktree_parent=tmp_path / "wts",
    )

    assert result.status == "opened"
    recorded_cwd = Path(record.read_text().strip()).resolve()
    assert recorded_cwd != local_repo.resolve(), "regen must run in the WORKTREE"
    show = subprocess.run(
        ["git", "-C", str(local_repo), "show", "--stat", "origin/ul/widget"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "docs/arch/generated/artifact.md" in show.stdout, (
        "regen-staged artifacts must ride the same commit"
    )
    assert "docs/wiki/terms/widget.md" in show.stdout


def test_failing_regen_is_fail_open(
    local_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auto_pr, "_ARCH_REGEN_ARGV", ("false",))
    monkeypatch.setattr(auto_pr, "_run_gh", _fake_gh)
    payload = local_repo / "note.md"
    payload.write_text("hello\n", encoding="utf-8")

    result = open_automated_pr(
        repo_root=local_repo,
        branch="ul/fail-open",
        files=[payload],
        title="feat(ul): note",
        body="",
        base="main",
        auto_merge=False,
        worktree_parent=tmp_path / "wts",
    )

    assert result.status == "opened", "a failing regen must never break the flow"


def test_missing_regen_tool_is_fail_open(
    local_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auto_pr, "_ARCH_REGEN_ARGV", (str(tmp_path / "does-not-exist"),)
    )
    monkeypatch.setattr(auto_pr, "_run_gh", _fake_gh)
    payload = local_repo / "note2.md"
    payload.write_text("hello\n", encoding="utf-8")

    result = open_automated_pr(
        repo_root=local_repo,
        branch="ul/enoent",
        files=[payload],
        title="feat(ul): note2",
        body="",
        base="main",
        auto_merge=False,
        worktree_parent=tmp_path / "wts",
    )

    assert result.status == "opened"


def test_toy_repo_without_makefile_unaffected(
    local_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default argv is `make arch-regen-stage`; in a repo with no Makefile
    it exits non-zero and the fail-open path keeps the pre-#12062 behaviour."""
    monkeypatch.setattr(auto_pr, "_run_gh", _fake_gh)
    payload = local_repo / "note3.md"
    payload.write_text("hello\n", encoding="utf-8")

    result = open_automated_pr(
        repo_root=local_repo,
        branch="ul/no-makefile",
        files=[payload],
        title="feat(ul): note3",
        body="",
        base="main",
        auto_merge=False,
        worktree_parent=tmp_path / "wts",
    )

    assert result.status == "opened"


