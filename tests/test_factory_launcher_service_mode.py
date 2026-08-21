"""``run-factory-isolated.sh`` SERVICE MODE (``HYDRAFLOW_FACTORY_SERVICE=1``, ADR-0135).

The launchd job must run the factory IN PLACE from the dedicated workspace
(``~/.hydraflow/factory-workspace/hydraflow``): macOS TCC blocks launchd
agents from ``~/Documents``, so the job cannot start from the dev checkout —
yet the launcher's "never reset --hard the dev checkout" guard refused to run
when DEV_ROOT == WORKSPACE. Service mode lifts exactly that one guard and
replaces it with a narrower invariant: the workspace must live under
``$HOME/.hydraflow/`` (the only place a throwaway factory workspace may live),
and it must already exist (the interactive installer clones it; the service
never does). Everything else — fetch, force-discard, reset to origin/$BRANCH,
``make env``, ``exec make run`` — is the unchanged non-service path.

Hermetic: a temp ``HOME``, a throwaway git origin, a real clone under
``$HOME/.hydraflow/``, and a fake ``make`` on ``PATH`` that records its
targets. No real server, no network, no launchctl.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "run-factory-isolated.sh"

# Isolate git from any global/system config (CI must not depend on it).
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


def _make_origin(root: Path) -> Path:
    """A throwaway origin on ``staging`` that carries the launcher itself, so
    the clone runs the script *in place* exactly like the launchd job does."""
    origin = root / "origin"
    (origin / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, origin / "scripts" / "run-factory-isolated.sh")
    (origin / ".gitignore").write_text(".env\n.venv/\n", encoding="utf-8")
    (origin / "README").write_text("v1\n", encoding="utf-8")
    _git(origin, "init", "-q", "-b", "staging")
    _git(origin, "add", "-A")
    _git(origin, "commit", "-qm", "c0")
    return origin


def _make_fake_make(root: Path) -> tuple[Path, Path]:
    """A ``make`` stand-in that logs its targets and exits 0."""
    bin_dir = root / "bin"
    bin_dir.mkdir()
    log = root / "make.log"
    fake = bin_dir / "make"
    fake.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\nexit 0\n', encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    return bin_dir, log


@pytest.fixture
def service_env(tmp_path: Path) -> dict[str, object]:
    home = tmp_path / "home"
    home.mkdir()
    origin = _make_origin(tmp_path)
    workspace = home / ".hydraflow" / "factory-workspace" / "hydraflow"
    workspace.parent.mkdir(parents=True)
    _git(tmp_path, "clone", "-q", str(origin), str(workspace))
    bin_dir, make_log = _make_fake_make(tmp_path)
    return {
        "home": home,
        "origin": origin,
        "workspace": workspace,
        "bin_dir": bin_dir,
        "make_log": make_log,
    }


def _run_service(
    env_parts: dict[str, object], *, workspace: Path | None = None
) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    assert bash is not None
    ws = workspace if workspace is not None else env_parts["workspace"]
    assert isinstance(ws, Path)
    script = ws / "scripts" / "run-factory-isolated.sh"
    if not script.exists():
        # A missing workspace still needs *a* launcher to run: use the dev one.
        script = SCRIPT
    env = {
        **os.environ,
        **_GIT_ENV,
        "HOME": str(env_parts["home"]),
        "PATH": f"{env_parts['bin_dir']}:{os.environ.get('PATH', '')}",
        "HYDRAFLOW_FACTORY_SERVICE": "1",
        "HYDRAFLOW_FACTORY_WORKSPACE": str(ws),
        "HYDRAFLOW_FACTORY_BRANCH": "staging",
    }
    return subprocess.run(
        [bash, str(script)],
        check=False,
        cwd=ws if ws.exists() else env_parts["home"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_service_mode_runs_in_place_and_syncs_to_origin(service_env) -> None:
    workspace: Path = service_env["workspace"]  # type: ignore[assignment]
    origin: Path = service_env["origin"]  # type: ignore[assignment]
    # Drift the workspace the way a factory run does: a dirty tracked file, an
    # untracked leftover, and a gitignored .env that must SURVIVE the sync.
    (workspace / "README").write_text("dirty\n", encoding="utf-8")
    (workspace / "review_logs").mkdir()
    (workspace / "review_logs" / "x.log").write_text("x", encoding="utf-8")
    (workspace / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    # ... and advance origin so the sync has something to pick up.
    (origin / "README").write_text("v2\n", encoding="utf-8")
    _git(origin, "commit", "-qam", "c1")
    origin_head = _git(origin, "rev-parse", "HEAD").stdout.strip()

    result = _run_service(service_env)

    assert result.returncode == 0, result.stderr
    # DEV_ROOT == WORKSPACE was accepted (no "dev checkout itself" abort) ...
    assert "dev checkout itself" not in result.stderr
    # ... the workspace was force-synced to origin/staging ...
    assert _git(workspace, "rev-parse", "HEAD").stdout.strip() == origin_head
    assert (workspace / "README").read_text() == "v2\n"
    assert not (workspace / "review_logs").exists()
    # ... the workspace's own gitignored .env is kept (nothing to copy from) ...
    assert (workspace / ".env").read_text() == "TOKEN=secret\n"
    # ... and the launch path ran: `make env` then `exec make run`.
    make_log: Path = service_env["make_log"]  # type: ignore[assignment]
    assert make_log.read_text().split() == ["env", "run"]


def test_service_mode_refuses_workspace_outside_dot_hydraflow(
    service_env, tmp_path: Path
) -> None:
    # A clone that is perfectly valid but lives outside $HOME/.hydraflow/ —
    # service mode must not reset --hard it (it could be anyone's checkout).
    elsewhere = tmp_path / "elsewhere" / "hydraflow"
    elsewhere.parent.mkdir()
    _git(tmp_path, "clone", "-q", str(service_env["origin"]), str(elsewhere))

    result = _run_service(service_env, workspace=elsewhere)

    assert result.returncode != 0
    assert ".hydraflow" in result.stderr
    # Untouched: still the original tip, nothing reset or cleaned.
    assert (elsewhere / "README").read_text() == "v1\n"
    make_log: Path = service_env["make_log"]  # type: ignore[assignment]
    assert not make_log.exists()


def test_service_mode_refuses_missing_workspace_instead_of_cloning(
    service_env,
) -> None:
    home: Path = service_env["home"]  # type: ignore[assignment]
    missing = home / ".hydraflow" / "factory-workspace" / "absent"

    result = _run_service(service_env, workspace=missing)

    assert result.returncode != 0
    assert "does not exist" in result.stderr
    assert "install_factory_service" in result.stderr
    assert not missing.exists()  # the service never clones
    make_log: Path = service_env["make_log"]  # type: ignore[assignment]
    assert not make_log.exists()


def test_non_service_guard_is_untouched_by_the_env_default(service_env) -> None:
    # Without HYDRAFLOW_FACTORY_SERVICE=1 the in-place guard must still fire —
    # the service flag is opt-in, never the default.
    workspace: Path = service_env["workspace"]  # type: ignore[assignment]
    bash = shutil.which("bash")
    assert bash is not None
    env = {
        **os.environ,
        **_GIT_ENV,
        "HOME": str(service_env["home"]),
        "PATH": f"{service_env['bin_dir']}:{os.environ.get('PATH', '')}",
        "HYDRAFLOW_FACTORY_WORKSPACE": str(workspace),
    }
    env.pop("HYDRAFLOW_FACTORY_SERVICE", None)
    result = subprocess.run(
        [bash, str(workspace / "scripts" / "run-factory-isolated.sh")],
        check=False,
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "dev checkout itself" in result.stderr


def test_header_documents_service_mode_env_and_invariant() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "HYDRAFLOW_FACTORY_SERVICE" in text
    assert "$HOME/.hydraflow/" in text
