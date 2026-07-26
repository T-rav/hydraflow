"""Regression: auto_pr fail-closed green-gate before auto-merge (#10672, Fix 2).

Root cause: ``src/auto_pr.py`` armed ``gh pr merge --auto --squash`` with no
client-side verification, trusting GitHub's *required* checks. When the staging
ruleset required only two trivial checks (``Detect Changes`` +
``discover-projects``), a PR whose ``Tests``/``CI Gate`` job was RED still
auto-merged (observed harm: #10663 poisoned staging HEAD). Fix 1 (require
``CI Gate`` on the ruleset) is already applied live; this is the CODE belt.

Fix 2 (this pin): before arming ``gh pr merge --auto``, the merge path queries
the PR's ``statusCheckRollup`` and only proceeds when EVERY non-skipped check
has settled SUCCESS. Fail-closed — a FAILURE, a still-PENDING check, an empty
rollup, or an unfetchable/unparseable rollup all block auto-merge. A config
kill-switch (``auto_pr_auto_merge_enabled``, default True) disables arming
entirely without a code change.

Pins:
- ``_status_check_rollup_is_green`` classifies green vs red/pending/empty.
- Sync ``open_automated_pr``: red / pending / garbage rollup → NO ``gh pr merge``;
  fully-green rollup → ``gh pr merge --auto`` IS invoked.
- Async ``open_automated_pr_async``: same green-gate on the shared finalize tail.
- Kill-switch ``auto_pr_auto_merge_enabled=False`` → NO ``gh pr merge`` even green.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ---------------------------------------------------------------------------
# Fixtures — a real local checkout pushing to a bare "origin" (mirrors
# tests/test_auto_pr.py so the full worktree→commit→push→create flow runs).
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


PR_URL = "https://github.com/x/y/pull/1"


def _rollup_json(rollup: list[dict[str, object]]) -> str:
    return json.dumps({"statusCheckRollup": rollup})


GREEN_ROLLUP = [
    {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"},
    {"__typename": "StatusContext", "state": "SUCCESS"},
]
RED_ROLLUP = [
    {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"},
    {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"},
]
PENDING_ROLLUP = [
    {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"},
    {"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None},
]


def _make_sync_gh(rollup_stdout: str | None, merge_calls: list[list[str]]):
    """Build a fake ``_run_gh`` that records ``gh pr merge`` invocations.

    ``rollup_stdout`` is returned for ``gh pr view --json statusCheckRollup``;
    ``None`` simulates a fetch that fails (non-zero exit) to exercise the
    fail-closed path.
    """

    def fake_gh(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if "create" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{PR_URL}\n", stderr="")
        if "view" in cmd:
            if rollup_stdout is None:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")
            return subprocess.CompletedProcess(cmd, 0, stdout=rollup_stdout, stderr="")
        if "merge" in cmd:
            merge_calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    return fake_gh


def _open_sync(local_repo: Path, branch: str) -> None:
    from auto_pr import open_automated_pr

    # Flat filename (branch names carry "/", which is fine for a git ref but
    # would create a phantom subdir as a path component here).
    target = local_repo / "change.txt"
    target.write_text("hello\n")
    open_automated_pr(
        repo_root=local_repo,
        branch=branch,
        files=[target],
        title="feat: x",
        body="body",
        base="main",
        auto_merge=True,
    )


# ---------------------------------------------------------------------------
# Classifier unit tests
# ---------------------------------------------------------------------------


def test_classifier_all_success_is_green() -> None:
    from auto_pr import _status_check_rollup_is_green

    assert _status_check_rollup_is_green(GREEN_ROLLUP) is True


def test_classifier_success_neutral_skipped_is_green() -> None:
    from auto_pr import _status_check_rollup_is_green

    rollup = [
        {"status": "COMPLETED", "conclusion": "SUCCESS"},
        {"status": "COMPLETED", "conclusion": "NEUTRAL"},
        {"status": "COMPLETED", "conclusion": "SKIPPED"},
    ]
    assert _status_check_rollup_is_green(rollup) is True


def test_classifier_empty_rollup_is_not_green() -> None:
    from auto_pr import _status_check_rollup_is_green

    # Fail-closed: a PR whose CI hasn't registered yet is never armed.
    assert _status_check_rollup_is_green([]) is False


@pytest.mark.parametrize(
    "bad", ["FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"]
)
def test_classifier_any_failing_conclusion_is_not_green(bad: str) -> None:
    from auto_pr import _status_check_rollup_is_green

    rollup = [
        {"status": "COMPLETED", "conclusion": "SUCCESS"},
        {"status": "COMPLETED", "conclusion": bad},
    ]
    assert _status_check_rollup_is_green(rollup) is False


def test_classifier_pending_checkrun_is_not_green() -> None:
    from auto_pr import _status_check_rollup_is_green

    assert _status_check_rollup_is_green(PENDING_ROLLUP) is False


def test_classifier_pending_status_context_is_not_green() -> None:
    from auto_pr import _status_check_rollup_is_green

    rollup = [{"__typename": "StatusContext", "state": "PENDING"}]
    assert _status_check_rollup_is_green(rollup) is False


# ---------------------------------------------------------------------------
# Sync merge-path integration
# ---------------------------------------------------------------------------


def test_sync_red_rollup_does_not_arm_auto_merge(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    merge_calls: list[list[str]] = []
    monkeypatch.setattr(
        "auto_pr._run_gh", _make_sync_gh(_rollup_json(RED_ROLLUP), merge_calls)
    )
    _open_sync(local_repo, "feature/red")
    assert merge_calls == [], "a red statusCheckRollup must NOT arm auto-merge"


def test_sync_pending_rollup_does_not_arm_auto_merge(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    merge_calls: list[list[str]] = []
    monkeypatch.setattr(
        "auto_pr._run_gh", _make_sync_gh(_rollup_json(PENDING_ROLLUP), merge_calls)
    )
    _open_sync(local_repo, "feature/pending")
    assert merge_calls == [], "a pending statusCheckRollup must NOT arm auto-merge"


def test_sync_unfetchable_rollup_fails_closed(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    merge_calls: list[list[str]] = []
    monkeypatch.setattr("auto_pr._run_gh", _make_sync_gh(None, merge_calls))
    _open_sync(local_repo, "feature/unfetchable")
    assert merge_calls == [], "an unfetchable rollup must fail closed (no auto-merge)"


def test_sync_garbage_rollup_fails_closed(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    merge_calls: list[list[str]] = []
    monkeypatch.setattr(
        "auto_pr._run_gh", _make_sync_gh("not json at all", merge_calls)
    )
    _open_sync(local_repo, "feature/garbage")
    assert merge_calls == [], "an unparseable rollup must fail closed (no auto-merge)"


def test_sync_green_rollup_arms_auto_merge(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    merge_calls: list[list[str]] = []
    monkeypatch.setattr(
        "auto_pr._run_gh", _make_sync_gh(_rollup_json(GREEN_ROLLUP), merge_calls)
    )
    _open_sync(local_repo, "feature/green")
    assert len(merge_calls) == 1, "a fully-green PR must still arm auto-merge"
    assert "--auto" in merge_calls[0]


def test_sync_kill_switch_disables_auto_merge_even_when_green(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from config import HydraFlowConfig
    from trace_collector import set_active_config

    cfg = HydraFlowConfig()
    object.__setattr__(cfg, "auto_pr_auto_merge_enabled", False)
    set_active_config(cfg)
    try:
        merge_calls: list[list[str]] = []
        monkeypatch.setattr(
            "auto_pr._run_gh", _make_sync_gh(_rollup_json(GREEN_ROLLUP), merge_calls)
        )
        _open_sync(local_repo, "feature/killswitch")
        assert merge_calls == [], "kill-switch must disable auto-merge even when green"
    finally:
        set_active_config(None)


# ---------------------------------------------------------------------------
# Async merge-path integration (shared finalize tail)
# ---------------------------------------------------------------------------


def _make_async_run(rollup_stdout: str, merge_calls: list[tuple[str, ...]]):
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
                return f"{PR_URL}\n".strip()
            if cmd[2] == "view":
                return rollup_stdout
            if cmd[2] == "merge":
                merge_calls.append(cmd)
                return ""
            return ""
        # Real git commands run against the scratch repo. run_subprocess's
        # contract raises RuntimeError (NOT CalledProcessError) on non-zero —
        # the finalize tail relies on that to detect a non-empty staged diff.
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


@pytest.mark.asyncio
async def test_async_green_rollup_arms_auto_merge(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from auto_pr import open_automated_pr_async

    merge_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        "subprocess_util.run_subprocess",
        _make_async_run(_rollup_json(GREEN_ROLLUP), merge_calls),
    )
    target = local_repo / "async_green.txt"
    target.write_text("hi\n")
    await open_automated_pr_async(
        repo_root=local_repo,
        branch="feature/async-green",
        files=[target],
        pr_title="feat: a",
        pr_body="b",
        base="main",
        auto_merge=True,
        preflight=(),
    )
    assert len(merge_calls) == 1, "async green PR must arm auto-merge"


@pytest.mark.asyncio
async def test_async_red_rollup_does_not_arm_auto_merge(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from auto_pr import open_automated_pr_async

    merge_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        "subprocess_util.run_subprocess",
        _make_async_run(_rollup_json(RED_ROLLUP), merge_calls),
    )
    target = local_repo / "async_red.txt"
    target.write_text("hi\n")
    await open_automated_pr_async(
        repo_root=local_repo,
        branch="feature/async-red",
        files=[target],
        pr_title="feat: a",
        pr_body="b",
        base="main",
        auto_merge=True,
        preflight=(),
    )
    assert merge_calls == [], "async red PR must NOT arm auto-merge"
