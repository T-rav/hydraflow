"""A bot PR must be armed at the moment its loop opens it (#12068).

The unit pins in `test_issue_12068_arm_gate_at_creation_time.py` assert what
the classifier RETURNS. This drives the real async `auto_pr` path a loop uses
and asserts the consequence: `gh pr merge --auto` is actually issued for a PR
whose checks have not settled — the shape that exists at `gh pr create` + 0s,
and the only shape the gate is ever consulted in.

That is the part a unit test cannot reach. The gate returning True is not the
same as the merge command being issued: the arm sits behind `auto_merge` and
the `auto_pr_auto_merge_enabled` kill-switch, and a fix to the classifier
alone would leave a disconnected arm looking exactly as it does now.

The settled-red case is the decoy. Without it, "a merge was issued" would pass
just as well against a build that armed unconditionally — which would throw
away #10663's belt, the harm #10672 was written for.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.scenario_loops

_PR_URL = "https://github.com/o/r/pull/7"

# The rollup a freshly-created PR really has: CI triggers on `pull_request`,
# so checks are unregistered or queued when the arm decision is made.
_AT_CREATION = [
    {"status": "QUEUED", "conclusion": None, "name": "CI Gate"},
    {"status": "IN_PROGRESS", "conclusion": None, "name": "quality (.)"},
]
_SETTLED_RED = [
    {"status": "COMPLETED", "conclusion": "SUCCESS", "name": "Detect Changes"},
    {"status": "COMPLETED", "conclusion": "FAILURE", "name": "CI Gate"},
]


def _repo(tmp_path: Path) -> Path:
    """A clone with a real `origin`, which the auto_pr finalize tail needs."""
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-q", "-b", "staging", str(remote)],
        check=True,
        capture_output=True,
    )
    root = tmp_path / "local"
    subprocess.run(
        ["git", "clone", "-q", str(remote), str(root)], check=True, capture_output=True
    )
    for cmd in (
        ["git", "checkout", "-q", "-b", "staging"],
        ["git", "config", "user.email", "t@example.com"],
        ["git", "config", "user.name", "T"],
    ):
        subprocess.run(cmd, cwd=root, check=True, capture_output=True)
    (root / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-qm", "seed"], cwd=root, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "push", "-q", "-u", "origin", "staging"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return root


def _scripted_gh(rollup: list[dict], merge_calls: list[tuple[str, ...]]):
    payload = json.dumps({"statusCheckRollup": rollup})

    async def fake_run(*cmd: str, cwd: Path | None = None, **_kw: object) -> str:
        if cmd[:2] == ("gh", "pr"):
            if cmd[2] == "create":
                return _PR_URL
            if cmd[2] == "view":
                return payload
            if cmd[2] == "merge":
                merge_calls.append(cmd)
            return ""
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


async def _open(root: Path, branch: str, name: str) -> None:
    from auto_pr import open_automated_pr_async

    target = root / name
    target.write_text("content\n")
    await open_automated_pr_async(
        repo_root=root,
        branch=branch,
        files=[target],
        pr_title="chore(diagram): regen",
        pr_body="body",
        base="staging",
        auto_merge=True,
        preflight=(),
    )


async def test_a_pr_whose_checks_have_not_settled_is_armed(
    tmp_path, monkeypatch
) -> None:
    """The #12068 defect: this issued no merge command at all."""
    root = _repo(tmp_path)
    merge_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        "subprocess_util.run_subprocess", _scripted_gh(_AT_CREATION, merge_calls)
    )

    await _open(root, "chore/regen-pending", "a.txt")

    assert merge_calls, (
        "no `gh pr merge` was issued for a freshly-opened bot PR — the PR is "
        "left open indefinitely, which is #12068"
    )
    assert any("--auto" in c for c in merge_calls)


async def test_a_pr_with_a_settled_failure_is_not_armed(tmp_path, monkeypatch) -> None:
    """The decoy — #10663's harm, and the whole point of keeping a belt."""
    root = _repo(tmp_path)
    merge_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        "subprocess_util.run_subprocess", _scripted_gh(_SETTLED_RED, merge_calls)
    )

    await _open(root, "chore/regen-red", "b.txt")

    assert merge_calls == [], (
        "armed auto-merge on a PR with an already-failing check — that is the "
        "#10663 harm #10672's belt exists to prevent"
    )
