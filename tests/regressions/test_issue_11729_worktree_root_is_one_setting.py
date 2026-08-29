"""Regression: the worktree creator and collector had no shared setting.

`scripts/hf_worktree.sh` passed `<dir>` to `git worktree add` VERBATIM, while
`WorkspaceGCLoop` swept a hardcoded list of harness directories. Two halves of
one concept, no shared value, drifting apart by construction — 47 of this
repo's 100 worktrees (37 GB) ended up where the collector could not see them
(#11729).

They now read one setting: `HYDRAFLOW_AGENT_WORKTREE_ROOT`, defaulting to
`<repo>/.claude/worktrees`.

A shell script cannot cheaply import `config`, so the default is spelled in
BOTH places. That duplication is the residual risk of the fix, and it is
exactly the "two tables over one vocabulary" shape the fix exists to remove —
so it is pinned here rather than trusted: the script's literal is read out of
the file and compared against the Python default.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from config import HydraFlowConfig  # noqa: E402

SCRIPT = REPO_ROOT / "scripts" / "hf_worktree.sh"

# HYDRAFLOW_AGENT_WORKTREE_ROOT:-$REPO_ROOT/<suffix>
_SHELL_DEFAULT = re.compile(
    r'HYDRAFLOW_AGENT_WORKTREE_ROOT:-\$REPO_ROOT/([^"\'}\s]+)'
)


def _shell_default_suffix() -> str:
    match = _SHELL_DEFAULT.search(SCRIPT.read_text(encoding="utf-8"))
    assert match, (
        "could not find the HYDRAFLOW_AGENT_WORKTREE_ROOT default in "
        f"{SCRIPT.name} — the guard cannot compare what it cannot parse, and "
        "a guard that silently finds nothing is worse than no guard"
    )
    return match.group(1)


def test_the_shell_and_python_defaults_are_the_same_path(tmp_path: Path) -> None:
    """The two spellings of one default must agree."""
    checkout = tmp_path / "myrepo"
    checkout.mkdir()
    config = HydraFlowConfig(repo_root=checkout)
    assert config.agent_worktree_root() == checkout / _shell_default_suffix()


def test_the_collector_lists_the_root_the_creator_writes_to(
    tmp_path: Path,
) -> None:
    """The whole point: the GC can see where bare names land."""
    checkout = tmp_path / "myrepo"
    checkout.mkdir()
    config = HydraFlowConfig(repo_root=checkout)
    assert config.agent_worktree_root() in config.worktree_gc_root_paths()


def test_the_override_moves_both_halves_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repointing the setting must move creator and collector as one."""
    checkout = tmp_path / "myrepo"
    checkout.mkdir()
    elsewhere = tmp_path / "elsewhere"
    monkeypatch.setenv("HYDRAFLOW_AGENT_WORKTREE_ROOT", str(elsewhere))
    config = HydraFlowConfig(repo_root=checkout)
    assert config.agent_worktree_root() == elsewhere
    assert elsewhere in config.worktree_gc_root_paths()


@pytest.mark.timeout(180)
def test_the_script_puts_a_bare_name_under_the_root(tmp_path: Path) -> None:
    """End-to-end: the behaviour, not just the constant.

    Uses a scratch repo, so it neither depends on nor disturbs this checkout.
    """
    repo = tmp_path / "scratch"
    repo.mkdir()

    def git(*args: str, cwd: Path = repo) -> None:
        subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "HOME": str(tmp_path)},
        )

    git("init", "-q", "-b", "main")
    git("-c", "user.email=t@e", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "seed")
    git("branch", "feature/x")

    out = subprocess.run(
        ["bash", str(SCRIPT), "barename", "feature/x"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "HOME": str(tmp_path)},
    )
    assert out.returncode == 0, f"script failed:\n{out.stdout}\n{out.stderr}"

    resolved = Path(out.stdout.strip().splitlines()[-1])
    expected = repo / _shell_default_suffix() / "barename"
    assert resolved.resolve() == expected.resolve(), (
        f"a bare name resolved to {resolved}, not under the agent root "
        f"{expected.parent} — the creator is writing where the collector "
        "cannot look"
    )
    assert resolved.is_dir(), "the resolved path is not a real worktree"


@pytest.mark.timeout(180)
def test_an_explicit_path_is_still_honoured_verbatim(tmp_path: Path) -> None:
    """A caller that needs a specific location keeps it."""
    repo = tmp_path / "scratch2"
    repo.mkdir()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "HOME": str(tmp_path)}

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)

    git("init", "-q", "-b", "main")
    git("-c", "user.email=t@e", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "seed")
    git("branch", "feature/y")

    out = subprocess.run(
        ["bash", str(SCRIPT), "sub/dir/here", "feature/y"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert out.returncode == 0, f"script failed:\n{out.stdout}\n{out.stderr}"
    resolved = Path(out.stdout.strip().splitlines()[-1])
    assert resolved.resolve() == (repo / "sub/dir/here").resolve(), (
        f"an explicit path was relocated to {resolved}; paths containing '/' "
        "must be honoured verbatim"
    )
