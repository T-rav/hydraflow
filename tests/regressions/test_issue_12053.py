"""Regression: direct-merge fallback when auto-merge is not allowed (#12053).

Root cause: ``src/auto_pr.py`` only ever tried ``gh pr merge --auto --squash``.
This repo has the repo-level "Allow auto-merge" setting OFF, so GitHub answers
``GraphQL: Auto merge is not allowed for this repository
(enablePullRequestAutoMerge)`` on every attempt — and the code logged a warning
and gave up. Every PR opened through this path was left open and unmerged with
no follow-up. Toggling the repo setting needs admin, so the fix is code-side.

Fix (this pin): when ``--auto`` fails, retry once with a direct
``gh pr merge --squash``. No CI poll loop is needed because the #10672
green-gate has already confirmed every non-skipped check settled SUCCESS
before either merge is attempted.

Pins:
- Sync ``open_automated_pr``: ``--auto`` failure → a direct ``gh pr merge
  --squash`` (no ``--auto``) follows; ``--auto`` success → no second call.
- Both merges failing stays best-effort: warning logged, ``status="opened"``,
  no ``AutoPrError``.
- The fallback does NOT bypass the green-gate: a red rollup still issues no
  merge command at all.
- Async ``open_automated_pr_async``: same fallback on the shared finalize tail.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

PR_URL = "https://github.com/x/y/pull/1"

# The exact stderr GitHub returns when the repo setting is off — the failure
# mode the source memory documented.
AUTO_MERGE_DISALLOWED_STDERR = (
    "GraphQL: Auto merge is not allowed for this repository "
    "(enablePullRequestAutoMerge)"
)

GREEN_ROLLUP: list[dict[str, object]] = [
    {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"},
    {"__typename": "StatusContext", "state": "SUCCESS"},
]
RED_ROLLUP: list[dict[str, object]] = [
    {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"},
]


def _rollup_json(rollup: list[dict[str, object]]) -> str:
    return json.dumps({"statusCheckRollup": rollup})


# ---------------------------------------------------------------------------
# Fixtures — a real local checkout pushing to a bare "origin", so the full
# worktree→commit→push→create→merge flow runs (mirrors tests/test_auto_pr.py).
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Sync path
# ---------------------------------------------------------------------------


def _make_sync_gh(
    *,
    rollup: str,
    merge_calls: list[list[str]],
    auto_fails: bool,
    direct_fails: bool = False,
):
    """Fake ``_run_gh`` recording every ``gh pr merge`` invocation.

    ``auto_fails`` makes the ``--auto`` attempt exit non-zero with the real
    "not allowed for this repository" stderr; ``direct_fails`` does the same
    for the plain ``--squash`` fallback.
    """

    def fake_gh(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if "create" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{PR_URL}\n", stderr="")
        if "view" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=rollup, stderr="")
        if "merge" in cmd:
            merge_calls.append(cmd)
            if "--auto" in cmd and auto_fails:
                return subprocess.CompletedProcess(
                    cmd, 1, stdout="", stderr=AUTO_MERGE_DISALLOWED_STDERR
                )
            if "--auto" not in cmd and direct_fails:
                return subprocess.CompletedProcess(
                    cmd, 1, stdout="", stderr="Pull request is not mergeable"
                )
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    return fake_gh


def _open_sync(local_repo: Path, branch: str):
    from auto_pr import open_automated_pr

    # Flat filename: branch names carry "/", which is fine for a git ref but
    # would create a phantom subdir as a path component here.
    target = local_repo / "change.txt"
    target.write_text("hello\n")
    return open_automated_pr(
        repo_root=local_repo,
        branch=branch,
        files=[target],
        title="feat: x",
        body="body",
        base="main",
        auto_merge=True,
    )


def test_sync_auto_merge_disallowed_falls_back_to_direct_squash_merge(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    merge_calls: list[list[str]] = []
    monkeypatch.setattr(
        "auto_pr._run_gh",
        _make_sync_gh(
            rollup=_rollup_json(GREEN_ROLLUP),
            merge_calls=merge_calls,
            auto_fails=True,
        ),
    )

    result = _open_sync(local_repo, "feature/fallback")

    assert len(merge_calls) == 2, (
        "a failed --auto must be retried as a direct merge, not abandoned"
    )
    assert "--auto" in merge_calls[0]
    assert merge_calls[1] == ["gh", "pr", "merge", PR_URL, "--squash"]
    assert result.status == "opened"


def test_sync_successful_auto_merge_does_not_issue_a_direct_merge(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    merge_calls: list[list[str]] = []
    monkeypatch.setattr(
        "auto_pr._run_gh",
        _make_sync_gh(
            rollup=_rollup_json(GREEN_ROLLUP),
            merge_calls=merge_calls,
            auto_fails=False,
        ),
    )

    _open_sync(local_repo, "feature/armed")

    assert len(merge_calls) == 1, (
        "an armed --auto must not be followed by a direct merge"
    )
    assert "--auto" in merge_calls[0]


def test_sync_both_merge_attempts_failing_stays_best_effort(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    merge_calls: list[list[str]] = []
    monkeypatch.setattr(
        "auto_pr._run_gh",
        _make_sync_gh(
            rollup=_rollup_json(GREEN_ROLLUP),
            merge_calls=merge_calls,
            auto_fails=True,
            direct_fails=True,
        ),
    )

    # No AutoPrError: the branch is pushed and the PR is open, which is the
    # contract callers depend on.
    result = _open_sync(local_repo, "feature/both-fail")

    assert len(merge_calls) == 2
    assert result.status == "opened"


def test_sync_fallback_does_not_bypass_the_green_gate(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    merge_calls: list[list[str]] = []
    monkeypatch.setattr(
        "auto_pr._run_gh",
        _make_sync_gh(
            rollup=_rollup_json(RED_ROLLUP),
            merge_calls=merge_calls,
            auto_fails=True,
        ),
    )

    _open_sync(local_repo, "feature/red-no-fallback")

    assert merge_calls == [], (
        "a red rollup must issue no merge command at all — the #10672 "
        "green-gate still guards the direct-merge fallback"
    )


# ---------------------------------------------------------------------------
# Async path (shared finalize tail)
# ---------------------------------------------------------------------------


def _make_async_run(
    *, rollup: str, merge_calls: list[tuple[str, ...]], auto_fails: bool
):
    """Fake ``run_subprocess`` honoring the real contract (raise on failure)."""

    async def fake_run(
        *cmd: str,
        cwd: Path | None = None,
        gh_token: str = "",
        timeout: float = 120.0,
        runner: object = None,
    ) -> str:
        del gh_token, timeout, runner
        if cmd[:2] == ("gh", "pr"):
            if cmd[2] == "create":
                return PR_URL
            if cmd[2] == "view":
                return rollup
            if cmd[2] == "merge":
                merge_calls.append(cmd)
                if "--auto" in cmd and auto_fails:
                    raise RuntimeError(AUTO_MERGE_DISALLOWED_STDERR)
            return ""
        # Real git commands against the scratch repo. run_subprocess raises
        # RuntimeError (NOT CalledProcessError) on non-zero — the finalize tail
        # relies on that to detect a non-empty staged diff.
        try:
            proc = subprocess.run(
                list(cmd),
                cwd=str(cwd) if cwd is not None else None,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(exc.stderr or str(exc)) from exc
        return proc.stdout.strip()

    return fake_run


async def _open_async(local_repo: Path, branch: str, filename: str):
    from auto_pr import open_automated_pr_async

    target = local_repo / filename
    target.write_text("hello\n")
    return await open_automated_pr_async(
        repo_root=local_repo,
        branch=branch,
        files=[target],
        pr_title="feat: x",
        pr_body="body",
        base="main",
        auto_merge=True,
        preflight=(),
    )


@pytest.mark.asyncio
async def test_async_auto_merge_disallowed_falls_back_to_direct_squash_merge(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    merge_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        "subprocess_util.run_subprocess",
        _make_async_run(
            rollup=_rollup_json(GREEN_ROLLUP),
            merge_calls=merge_calls,
            auto_fails=True,
        ),
    )

    result = await _open_async(local_repo, "feature/async-fallback", "async_fb.txt")

    assert len(merge_calls) == 2, (
        "the async finalize tail must retry a failed --auto as a direct merge"
    )
    assert "--auto" in merge_calls[0]
    assert merge_calls[1] == ("gh", "pr", "merge", PR_URL, "--squash")
    assert result.status == "opened"


@pytest.mark.asyncio
async def test_async_successful_auto_merge_does_not_issue_a_direct_merge(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    merge_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        "subprocess_util.run_subprocess",
        _make_async_run(
            rollup=_rollup_json(GREEN_ROLLUP),
            merge_calls=merge_calls,
            auto_fails=False,
        ),
    )

    await _open_async(local_repo, "feature/async-armed", "async_armed.txt")

    assert len(merge_calls) == 1, (
        "an armed --auto must not be followed by a direct merge"
    )
