"""Regression: born-red bot PRs are blocked by the auto_pr pre-flight gate.

#10013: factory bots opened PRs that deterministic local gates would have
caught (#9964 suppression-ratchet red, #9994 regressions-guard red), each
burning a full CI cycle. The gate runs the ratchet/regressions pytest stage
inside the PR worktree BEFORE anything is committed, pushed, or turned into
a PR.

This is the one non-faked layer: a REAL pytest subprocess runs a REAL red
ratchet test inside the ephemeral worktree of a scratch repo, and the
assertions prove the PR never happens — no branch on the remote, no
``gh pr create``. Only the tool launcher prefix is swapped (``uv run`` →
``sys.executable -m``) so the scratch repo does not need a uv project.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


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
    (local / "README.md").write_text("init\n")
    subprocess.run(["git", "-C", str(local), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(local), "commit", "-m", "init"], check=True)
    subprocess.run(
        ["git", "-C", str(local), "push", "-u", "origin", "main"], check=True
    )
    return local


@pytest.mark.asyncio
async def test_real_red_ratchet_in_worktree_blocks_pr(
    local_repo: Path, bare_remote: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import auto_pr
    from auto_pr import generate_and_open_pr_async

    # Run gate tools via this test's interpreter instead of `uv run` so the
    # scratch repo needs no uv project; the pytest run itself is real.
    monkeypatch.setattr(auto_pr, "_PREFLIGHT_RUNNER_PREFIX", (sys.executable, "-m"))

    gh_calls: list[tuple[str, ...]] = []

    async def fake_run(
        *cmd: str,
        cwd: Path | None = None,
        gh_token: str = "",
        timeout: float = 120.0,
        runner: object = None,
    ) -> str:
        del gh_token, runner
        if cmd[0] == "gh":
            gh_calls.append(tuple(cmd))
            return "https://github.com/x/y/pull/9"
        try:
            return subprocess.run(
                list(cmd),
                cwd=str(cwd) if cwd is not None else None,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout,
            ).stdout.strip()
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(exc.stdout or exc.stderr or str(exc)) from exc

    monkeypatch.setattr("subprocess_util.run_subprocess", fake_run)

    async def _generate(worktree: Path) -> None:
        # The bot's "change": a ratchet test that is red in the worktree,
        # exactly like a new suppression pushing the count over baseline.
        tests_dir = worktree / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_disturbance_ratchet.py").write_text(
            "def test_suppression_count_within_baseline() -> None:\n"
            '    raise AssertionError("suppression count exceeded baseline")\n'
        )

    result = await generate_and_open_pr_async(
        repo_root=local_repo,
        branch="bot/born-red",
        generate=_generate,
        path_specs=["tests"],
        pr_title="chore: born red",
        pr_body="body",
        raise_on_failure=False,
        preflight=("pytest",),
    )

    assert result.status == "failed"
    assert result.preflight_stage == "pytest"
    assert result.error is not None
    assert "stage=pytest" in result.error

    # The PR never happened: nothing pushed, no gh pr create.
    assert gh_calls == []
    ls_remote = subprocess.run(
        ["git", "ls-remote", "--heads", str(bare_remote), "bot/born-red"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert ls_remote.stdout.strip() == ""
