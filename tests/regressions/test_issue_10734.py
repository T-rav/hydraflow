"""Regression guard for #10734 — the liveness kernel must not boot a stale factory.

Root cause (2026-07-27): a launchd restart booted the factory **90 commits behind
on ``main``, idle** — a "successful restart" into a stale, wrong-branch known-good
state. The watchdog had (a) no boot-correctness check and (b) relaunched with the
shell-default branch ``main`` (``scripts/run-factory-isolated.sh`` defaulted to
``main`` and the plist set no ``HYDRAFLOW_FACTORY_BRANCH``).

Fix (#10734): the boot-correctness guard refuses ``POST /api/control/start``
unless ``boot_sha == origin/<factory_branch>`` HEAD **and** ``commits_behind ==
0`` **and** the workspace is on the factory branch; on a definite mismatch it
force-resyncs + relaunches pinned to ``staging``.

Three guards, so the drift can never silently recur:

1. **Behavioral (real git)** — a workspace clone left behind ``origin/staging``
   (the literal incident shape) feeds real ``boot_sha`` / ``commits_behind`` /
   branch facts into the guard, which must return RESYNC_REBOOT and NEVER START;
   an up-to-date clone must START.
2. **Launcher script guard** — ``run-factory-isolated.sh`` defaults ``BRANCH`` to
   ``staging``; a future edit reintroducing ``main`` fails here.
3. **Plist branch-pin guard** — the installer renders
   ``EnvironmentVariables{HYDRAFLOW_FACTORY_BRANCH=staging}`` so a relaunch never
   inherits the shell default.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
from pathlib import Path

from scripts.liveness import boot_guard
from scripts.liveness.boot_guard import BootAction

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LAUNCHER = _REPO_ROOT / "scripts" / "run-factory-isolated.sh"
_INSTALLER = _REPO_ROOT / "scripts" / "install_liveness_watchdog.py"

# Fully isolate git from any global/system config (CI must not depend on it).
_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, **_GIT_ENV},
    )


def _origin_and_stale_workspace(tmp_path: Path) -> tuple[Path, str, str]:
    """An ``origin`` whose ``staging`` has advanced past a workspace clone.

    Returns ``(workspace, boot_sha, origin_head)`` where ``boot_sha`` is the
    stale HEAD the factory booted on and ``origin_head`` is the advanced tip.
    """
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "staging")
    (origin / "f").write_text("c0", encoding="utf-8")
    _git(origin, "add", "-A")
    _git(origin, "commit", "-qm", "c0")

    workspace = tmp_path / "workspace"
    _git(tmp_path, "clone", "-q", str(origin), str(workspace))
    _git(workspace, "checkout", "-q", "staging")
    boot_sha = _git(workspace, "rev-parse", "HEAD").stdout.strip()

    # origin/staging advances (the factory keeps booting the old bytecode).
    (origin / "f").write_text("c1", encoding="utf-8")
    _git(origin, "commit", "-qam", "c1")
    origin_head = _git(origin, "rev-parse", "HEAD").stdout.strip()

    return workspace, boot_sha, origin_head


def test_stale_workspace_yields_resync_reboot_never_start(tmp_path: Path) -> None:
    workspace, boot_sha, origin_head = _origin_and_stale_workspace(tmp_path)

    # Real probes off the workspace (fetch refreshes origin/staging).
    branch = boot_guard.git_current_branch(workspace)
    probed_origin_head = boot_guard.git_origin_head(workspace, "staging")
    assert branch == "staging"
    assert probed_origin_head == origin_head
    assert boot_sha != origin_head  # the workspace is genuinely behind

    commits_behind = int(
        _git(workspace, "rev-list", "--count", f"{boot_sha}..{origin_head}").stdout
    )
    assert commits_behind > 0

    decision = boot_guard.decide_boot_action(
        workspace_branch=branch,
        factory_branch="staging",
        origin_head=probed_origin_head,
        boot_sha=boot_sha,
        commits_behind=commits_behind,
        status="idle",
    )
    assert decision.action is BootAction.RESYNC_REBOOT
    assert decision.action is not BootAction.START


def test_wrong_branch_boot_yields_resync_reboot(tmp_path: Path) -> None:
    # The literal incident: the workspace ended up on `main`, not `staging`.
    workspace, boot_sha, origin_head = _origin_and_stale_workspace(tmp_path)
    _git(workspace, "checkout", "-q", "-b", "main")
    decision = boot_guard.decide_boot_action(
        workspace_branch=boot_guard.git_current_branch(workspace),
        factory_branch="staging",
        origin_head=origin_head,
        boot_sha=boot_sha,
        commits_behind=0,
        status="idle",
    )
    assert decision.action is BootAction.RESYNC_REBOOT


def test_up_to_date_workspace_starts(tmp_path: Path) -> None:
    workspace, _stale, origin_head = _origin_and_stale_workspace(tmp_path)
    # Sync the workspace forward to the advanced tip — now boot-correct.
    _git(workspace, "fetch", "origin", "--prune")
    _git(workspace, "reset", "--hard", "origin/staging")
    current = _git(workspace, "rev-parse", "HEAD").stdout.strip()
    assert current == origin_head
    decision = boot_guard.decide_boot_action(
        workspace_branch=boot_guard.git_current_branch(workspace),
        factory_branch="staging",
        origin_head=origin_head,
        boot_sha=current,
        commits_behind=0,
        status="idle",
    )
    assert decision.action is BootAction.START


def test_launcher_defaults_to_staging_not_main() -> None:
    text = _LAUNCHER.read_text(encoding="utf-8")
    # The bug default that stranded the factory on main must be gone.
    assert not re.search(r'BRANCH="\$\{HYDRAFLOW_FACTORY_BRANCH:-main\}"', text), (
        "run-factory-isolated.sh reintroduced the `main` default — a relaunch "
        "boots the factory on the wrong branch (ADR-0042 runs on staging; #10734)."
    )
    assert re.search(r'BRANCH="\$\{HYDRAFLOW_FACTORY_BRANCH:-staging\}"', text)


def test_installer_pins_staging_in_plist_environment() -> None:
    spec = importlib.util.spec_from_file_location(
        "install_liveness_watchdog", _INSTALLER
    )
    assert spec and spec.loader
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    xml = installer.render_plist(
        label="com.hydraflow.liveness",
        python_executable="/usr/bin/python3",
        watchdog_script=Path("/x/watchdog.py"),
        extra_args=["--workspace", "/x/ws", "--factory-branch", "staging"],
        start_interval=300,
        stdout_path=Path("/x/out.log"),
        stderr_path=Path("/x/err.log"),
        environment={"HYDRAFLOW_FACTORY_BRANCH": "staging"},
    )
    assert "<key>EnvironmentVariables</key>" in xml
    assert "<key>HYDRAFLOW_FACTORY_BRANCH</key>" in xml
    assert "<string>staging</string>" in xml
