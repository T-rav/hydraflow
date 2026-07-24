"""Regression guard for #10408 — the isolated factory launcher must force-sync.

Root cause: ``scripts/run-factory-isolated.sh`` runs under ``set -euo pipefail``
and synced the disposable factory workspace to ``origin/$BRANCH`` with a *plain*
checkout::

    git -C "$WORKSPACE" fetch origin --prune
    git -C "$WORKSPACE" checkout "$BRANCH"          # aborts on a dirty tracked file
    git -C "$WORKSPACE" reset --hard "origin/$BRANCH"  # never reached

A plain ``git checkout <branch>`` refuses to overwrite an uncommitted tracked
change, so under ``set -e`` that abort killed the whole launch *before* the
``reset --hard`` that would have cleaned it. In production an agent left a stray
``pyproject.toml`` coverage bump in the workspace; from then on every
``make factory`` aborted at the checkout while a previously-launched server kept
running — the factory silently ran 51+ commits behind, holding a stale in-memory
board and spinning on already-closed issues, yet looking healthy.

Fix: force-discard all working-tree churn, exactly as the script's own comment
promises ("discarding its working-tree churn here is the whole point")::

    git -C "$WORKSPACE" checkout -f "$BRANCH"     # discard local changes, never abort
    git -C "$WORKSPACE" reset --hard "origin/$BRANCH"
    git -C "$WORKSPACE" clean -fd                 # drop untracked leftovers, keep gitignored caches

Two guards, so the drift can never silently recur:

1. **Behavioral** — replicating the script's exact sync sequence against a real
   throwaway clone that has BOTH a dirty tracked file and untracked leftovers
   force-syncs it clean to ``origin/$BRANCH``; and the OLD plain ``checkout``
   really does abort on that dirty file (the bug trigger is genuine).
   ``clean -fd`` (no ``-x``) must preserve gitignored caches/``.venv``.

2. **Script guard** — the live launcher actually uses the force variants, so a
   future edit that reintroduces the bare ``checkout "$BRANCH"`` fails here
   instead of silently stranding the factory again.

The script's clone / ``.env`` copy / ``make env`` / ``make run`` steps are not
exercised (heavy, side-effectful); this pins the git sync mechanic that broke.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LAUNCHER = _REPO_ROOT / "scripts" / "run-factory-isolated.sh"

# Fully isolate git from any global/system config (CI must not depend on it).
_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    import os

    env = {**os.environ, **_GIT_ENV}
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=check,
        env=env,
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def workspace_and_origin(tmp_path: Path) -> tuple[Path, Path]:
    """A throwaway ``origin`` whose ``main`` differs from a ``stale`` branch, plus
    a ``workspace`` clone checked out on ``stale`` with a dirty tracked file,
    untracked leftovers, and a gitignored cache — mirroring the real workspace."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    _write(origin / "pyproject.toml", "fail_under = 88.0\n")
    _write(origin / ".gitignore", ".venv/\n")
    _git(origin, "add", "-A")
    _git(origin, "commit", "-qm", "c0 main")
    # A `stale` branch whose pyproject.toml DIFFERS from main's tip, so checking
    # out main over a dirty working tree is a genuine overwrite conflict.
    _git(origin, "checkout", "-q", "-b", "stale")
    _write(origin / "pyproject.toml", "fail_under = 89.5\n")
    _git(origin, "commit", "-qam", "cs stale")
    _git(origin, "checkout", "-q", "main")

    workspace = tmp_path / "workspace"
    _git(tmp_path, "clone", "-q", str(origin), str(workspace))
    _git(workspace, "checkout", "-q", "stale")  # HEAD on stale (pyproject 89.5)

    # Dirty tracked file (the real trigger) + untracked agent leftovers + a
    # gitignored cache that must survive `clean -fd`.
    _write(workspace / "pyproject.toml", "fail_under = 90.6\n")
    _write(workspace / "review_logs" / "run.log", "leftover\n")
    _write(workspace / "tests" / "regressions" / "test_issue_9999.py", "# stray\n")
    _write(workspace / ".venv" / "marker", "keep-me\n")
    return workspace, origin


def test_plain_checkout_aborts_on_dirty_tracked_file(workspace_and_origin) -> None:
    """The bug trigger is genuine: the OLD plain `checkout $BRANCH` fails."""
    workspace, _ = workspace_and_origin
    result = _git(workspace, "checkout", "main", check=False)
    assert result.returncode != 0, "plain checkout unexpectedly succeeded — bug repro is stale"
    assert "would be overwritten" in result.stderr.lower()


def test_force_sync_recovers_dirty_workspace(workspace_and_origin) -> None:
    """The fix's sequence force-syncs the workspace clean to origin/main."""
    workspace, _ = workspace_and_origin

    # Exactly the launcher's post-fix sync sequence.
    _git(workspace, "fetch", "origin", "--prune")
    _git(workspace, "checkout", "-f", "main")
    _git(workspace, "reset", "--hard", "origin/main")
    _git(workspace, "clean", "-fd")

    # On origin/main, tree clean, local churn discarded.
    head = _git(workspace, "rev-parse", "HEAD").stdout.strip()
    origin_main = _git(workspace, "rev-parse", "origin/main").stdout.strip()
    assert head == origin_main
    assert _git(workspace, "status", "--porcelain").stdout.strip() == ""
    assert (workspace / "pyproject.toml").read_text() == "fail_under = 88.0\n"

    # Untracked agent leftovers removed …
    assert not (workspace / "review_logs").exists()
    assert not (workspace / "tests" / "regressions" / "test_issue_9999.py").exists()
    # … but gitignored caches/.venv preserved (clean -fd has no -x).
    assert (workspace / ".venv" / "marker").read_text() == "keep-me\n"


def test_launcher_uses_force_sync_variants() -> None:
    """The live launcher must use the force variants, not a bare checkout."""
    text = _LAUNCHER.read_text(encoding="utf-8")
    # The bare form that aborts on dirty tracked files must be gone.
    assert not re.search(r'checkout\s+"\$BRANCH"', text), (
        "run-factory-isolated.sh reintroduced a bare `checkout \"$BRANCH\"` — "
        "it aborts on a dirty tracked file under set -e and strands the factory "
        "on a stale boot (#10408). Use `checkout -f`."
    )
    assert re.search(r'checkout\s+-f\s+"\$BRANCH"', text)
    assert re.search(r'reset\s+--hard\s+"origin/\$BRANCH"', text)
    assert re.search(r'clean\s+-fd\b', text)
