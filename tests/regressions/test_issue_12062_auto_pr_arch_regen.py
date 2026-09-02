"""Regression #12062: bot PRs commit stale generated arch artifacts.

TermProposerLoop's first post-v1.0.1 cycle failed at commit time: its term
file is an INPUT to docs/arch/generated/, the auto_pr flow never regenerated,
and the worktree pre-commit hook rejected the commit ("docs/arch/generated/
is out of sync — Run: make arch-regen-stage"). Every caller of
``generate_and_open_pr_async`` / ``open_automated_pr_async`` whose files
touch arch inputs failed identically.

Pins, on the ASYNC path every production caller uses (the first shipped fix
was wired only into the sync ``open_automated_pr``, which has zero production
callers — caught in review):

1. regen runs in the WORKTREE between staging and commit, and what it stages
   rides the same commit;
2. the drift-exempt volatile artifacts (``arch.runner._DRIFT_EXEMPT``) ride
   along with substantive changes per the documented substantive_specs
   contract, and are unstaged only when they would be the commit's sole
   content — so a no-input caller cannot be turned into a spurious PR
   (pass-2 review: an unconditional exclusion silently broke ride-along);
3. failing / missing regen tools are fail-open;
4. ``auto_pr._VOLATILE_ARCH_ARTIFACTS`` stays bound to the runner's set.
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

import auto_pr
from auto_pr import generate_and_open_pr_async, open_automated_pr


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


class _GitPassthroughGhStub:
    """The established pattern for real-git async-path tests: git commands run
    for real; gh commands are stubbed and recorded."""

    def __init__(self) -> None:
        self.gh_calls: list[tuple[str, ...]] = []

    async def __call__(
        self,
        *cmd: str,
        cwd: Any = None,
        gh_token: str = "",
        timeout: float = 120.0,
        runner: Any = None,
    ) -> str:
        del gh_token, timeout, runner
        if cmd and cmd[0] == "gh":
            self.gh_calls.append(cmd)
            if cmd[:3] == ("gh", "pr", "create"):
                return "https://github.com/acme/widget/pull/99\n"
            return ""
        proc = subprocess.run(
            list(cmd), check=False, cwd=cwd, capture_output=True, text=True, timeout=60
        )
        if proc.returncode != 0:
            raise RuntimeError(f"{cmd}: {proc.stderr}")
        return proc.stdout.strip()


def _write_recording_regen(tmp_path: Path) -> tuple[Path, Path]:
    """Stand-in for `make arch-regen-stage`: records its cwd, then writes AND
    stages one substantive artifact plus one volatile (drift-exempt) one —
    the observable shape of the real target's blanket `git add`."""
    record = tmp_path / "regen-cwd.txt"
    script = tmp_path / "fake-regen.sh"
    script.write_text(
        "#!/bin/sh\n"
        f'pwd > "{record}"\n'
        "mkdir -p docs/arch/generated\n"
        "echo regenerated > docs/arch/generated/artifact.md\n"
        "echo volatile-window > docs/arch/generated/changelog.md\n"
        "git add docs/arch/generated\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script, record


@pytest.mark.asyncio
async def test_async_path_regen_rides_commit_and_excludes_volatile(
    local_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The path TermProposerLoop actually uses: generate_and_open_pr_async."""
    script, record = _write_recording_regen(tmp_path)
    stub = _GitPassthroughGhStub()
    monkeypatch.setattr(auto_pr, "_ARCH_REGEN_ARGV", (str(script),))
    monkeypatch.setattr("subprocess_util.run_subprocess", stub)

    async def generate(worktree: Path) -> None:
        terms = worktree / "docs" / "wiki" / "terms"
        terms.mkdir(parents=True)
        (terms / "widget.md").write_text("# widget\n", encoding="utf-8")

    result = await generate_and_open_pr_async(
        repo_root=local_repo,
        branch="ul/widget",
        generate=generate,
        path_specs=["docs/wiki/terms"],
        pr_title="feat(ul): widget",
        pr_body="",
        base="main",
        auto_merge=False,
        worktree_parent=tmp_path / "wts",
        preflight=[],
    )

    assert result.status == "opened", result
    recorded_cwd = Path(record.read_text().strip()).resolve()
    assert recorded_cwd != local_repo.resolve(), "regen must run in the WORKTREE"
    show = subprocess.run(
        ["git", "-C", str(local_repo), "show", "--stat", "origin/ul/widget"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "docs/wiki/terms/widget.md" in show.stdout
    assert "docs/arch/generated/artifact.md" in show.stdout, (
        "regen-staged artifacts must ride the same commit"
    )
    assert "changelog.md" in show.stdout, (
        "volatile artifacts RIDE ALONG when substantive content changed — "
        "the documented substantive_specs contract (pass-2 review of #12063)"
    )


@pytest.mark.asyncio
async def test_async_volatile_only_regen_stays_no_diff(
    local_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller whose generate stages nothing must stay no-diff even when
    regen churns the volatile artifacts — no spurious PRs. (In the real repo
    the regen is deterministic, but the volatile git-log views churn on every
    window shift; this fake stages ONLY volatile content.)"""
    record = tmp_path / "regen-cwd.txt"
    script = tmp_path / "volatile-only-regen.sh"
    script.write_text(
        "#!/bin/sh\n"
        f'pwd > "{record}"\n'
        "mkdir -p docs/arch/generated\n"
        "echo volatile-window > docs/arch/generated/changelog.md\n"
        "git add docs/arch/generated\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    stub = _GitPassthroughGhStub()
    monkeypatch.setattr(auto_pr, "_ARCH_REGEN_ARGV", (str(script),))
    monkeypatch.setattr("subprocess_util.run_subprocess", stub)

    async def generate(worktree: Path) -> None:
        return None

    result = await generate_and_open_pr_async(
        repo_root=local_repo,
        branch="ul/volatile-only",
        generate=generate,
        path_specs=[],
        pr_title="feat(ul): nothing",
        pr_body="",
        base="main",
        auto_merge=False,
        worktree_parent=tmp_path / "wts",
        preflight=[],
        raise_on_failure=False,
    )

    assert result.status == "no-diff", result
    assert not any(c[:3] == ("gh", "pr", "create") for c in stub.gh_calls)


@pytest.mark.asyncio
async def test_async_missing_regen_tool_is_fail_open(
    local_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = _GitPassthroughGhStub()
    monkeypatch.setattr(auto_pr, "_ARCH_REGEN_ARGV", (str(tmp_path / "missing"),))
    monkeypatch.setattr("subprocess_util.run_subprocess", stub)

    async def generate(worktree: Path) -> None:
        (worktree / "note.md").write_text("hello\n", encoding="utf-8")

    result = await generate_and_open_pr_async(
        repo_root=local_repo,
        branch="ul/fail-open",
        generate=generate,
        path_specs=["note.md"],
        pr_title="feat(ul): note",
        pr_body="",
        base="main",
        auto_merge=False,
        worktree_parent=tmp_path / "wts",
        preflight=[],
    )

    assert result.status == "opened", "a failing regen must never break the flow"


def test_volatile_set_bound_to_arch_runner() -> None:
    """_VOLATILE_ARCH_ARTIFACTS is a deliberate copy (arch.runner is heavy);
    this binding is what keeps it from drifting."""
    from arch.runner import _DRIFT_EXEMPT

    assert set(auto_pr._VOLATILE_ARCH_ARTIFACTS) == set(_DRIFT_EXEMPT)


def _fake_gh(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        cmd, 0, stdout="https://github.com/x/y/pull/1\n", stderr=""
    )


def test_sync_twin_regen_runs_in_worktree(
    local_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sync entry point shares the argv seam and exclusion contract."""
    script, record = _write_recording_regen(tmp_path)
    monkeypatch.setattr(auto_pr, "_ARCH_REGEN_ARGV", (str(script),))
    monkeypatch.setattr(auto_pr, "_run_gh", _fake_gh)
    payload = local_repo / "note.md"
    payload.write_text("hello\n", encoding="utf-8")

    result = open_automated_pr(
        repo_root=local_repo,
        branch="ul/sync",
        files=[payload],
        title="feat(ul): note",
        body="",
        base="main",
        auto_merge=False,
        worktree_parent=tmp_path / "wts",
    )

    assert result.status == "opened"
    recorded_cwd = Path(record.read_text().strip()).resolve()
    assert recorded_cwd != local_repo.resolve()
    show = subprocess.run(
        ["git", "-C", str(local_repo), "show", "--stat", "origin/ul/sync"],
        capture_output=True,
        text=True,
        check=True,
    )
    # note.md is substantive, so the volatile artifact rides along (the
    # documented contract) — the exclusion fires only for volatile-only stages.
    assert "changelog.md" in show.stdout


def test_sync_twin_toy_repo_without_makefile_unaffected(
    local_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auto_pr, "_run_gh", _fake_gh)
    payload = local_repo / "note2.md"
    payload.write_text("hello\n", encoding="utf-8")

    result = open_automated_pr(
        repo_root=local_repo,
        branch="ul/no-makefile",
        files=[payload],
        title="feat(ul): note2",
        body="",
        base="main",
        auto_merge=False,
        worktree_parent=tmp_path / "wts",
    )

    assert result.status == "opened"
