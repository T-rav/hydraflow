#!/usr/bin/env python3
"""Install/uninstall the launchd agent that runs the factory as a service (ADR-0135).

Renders ``~/Library/LaunchAgents/com.hydraflow.factory.plist`` that runs
``scripts/run-factory-isolated.sh`` **in place from the dedicated workspace**
(``~/.hydraflow/factory-workspace/hydraflow``) in SERVICE MODE
(``HYDRAFLOW_FACTORY_SERVICE=1``), ``KeepAlive`` + ``RunAtLoad``, then
(re)loads it via ``launchctl``. Idempotent: running install twice just
re-renders and reloads the same agent; ``--uninstall`` unloads and removes
it (the liveness knob is left alone).

Why the workspace, not the dev checkout: macOS TCC denies launchd agents
``~/Documents`` (``make: getcwd: Operation not permitted`` → ``No rule to make
target 'factory'``), which is how the factory sat down 15 of 31 days. The
workspace lives under ``~/.hydraflow/`` — outside TCC — and the launcher's
service mode only ever accepts a workspace there.

Liveness integration: ``~/.hydraflow/liveness/restart.knob`` (seeded by
``scripts/install_liveness_watchdog.py`` with just ``RESTART_ENABLED=true``)
gains ``RESTART_LABEL=com.hydraflow.factory`` so the watchdog's
``attempt_restart()`` has a ``launchctl kickstart -k`` target instead of
logging "no RESTART_COMMAND/RESTART_LABEL configured — skipping restart".
The line is appended only when neither key is present; existing operator
keys are never overwritten (same contract as ``seed_restart_knob``).

Like the liveness installer this is a deliberately manual, operator-run step
from the dev checkout — NOT something the factory installs on itself. If the
workspace does not exist yet it is cloned here (interactively, from this
checkout's ``origin``); the service itself never clones.

Usage::

    scripts/install_factory_service.py                 # install/update
    scripts/install_factory_service.py --uninstall      # remove
    scripts/install_factory_service.py --dry-run        # render + print only

Recipe (see docs/wiki/dependencies.md "Factory-as-service install recipe")::

    python scripts/install_factory_service.py
    python scripts/install_liveness_watchdog.py

macOS only (launchd). Exits 1 with a clear message on any other platform.
"""

from __future__ import annotations

import argparse
import logging
import os
import platform
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("install_factory_service")

_LABEL = "com.hydraflow.factory"
_REPO_ROOT = Path(__file__).resolve().parent.parent
_LAUNCHER_RELATIVE = Path("scripts") / "run-factory-isolated.sh"
_DEFAULT_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{_LABEL}.plist"
_DEFAULT_WORKSPACE = Path.home() / ".hydraflow" / "factory-workspace" / "hydraflow"
#: ADR-0042: the factory runs on staging; main advances only via RC promotion.
_DEFAULT_FACTORY_BRANCH = "staging"
#: The earlier (failed) launchd attempt already logged to these names on the
#: host — reuse them rather than orphaning the old files.
_DEFAULT_LOG_DIR = Path.home() / ".hydraflow"
_STDOUT_NAME = "factory-launchd.out.log"
_STDERR_NAME = "factory-launchd.err.log"
_DEFAULT_KNOB_PATH = Path.home() / ".hydraflow" / "liveness" / "restart.knob"
#: launchd restarts a KeepAlive job that exits; never tighter than this, so a
#: launcher that dies at boot (bad .env, offline) cannot hot-loop.
_THROTTLE_INTERVAL_SECONDS = 60


def _service_path(home: Path) -> str:
    """PATH for the job: launchd's default lacks uv/node/gh/docker."""
    return ":".join(
        [
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            str(home / ".local" / "bin"),
        ]
    )


def render_plist(
    *,
    label: str,
    workspace: Path,
    factory_branch: str,
    home: Path,
    stdout_path: Path,
    stderr_path: Path,
) -> str:
    """Return the launchd plist XML as a string. Pure — no I/O.

    ``ProgramArguments`` is ``/bin/bash <workspace>/scripts/run-factory-isolated.sh``
    with ``WorkingDirectory`` = the workspace: the job runs *in place*, which
    the launcher's service mode (``HYDRAFLOW_FACTORY_SERVICE=1``) permits
    only for a workspace under ``$HOME/.hydraflow/``. ``HOME`` and ``PATH``
    are pinned explicitly because launchd agents inherit neither a login
    shell's profile nor Homebrew's bin.
    """

    def _esc(value: str) -> str:
        return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    args = ["/bin/bash", str(workspace / _LAUNCHER_RELATIVE)]
    program_args_xml = "\n".join(f"        <string>{_esc(a)}</string>" for a in args)
    environment = {
        "HYDRAFLOW_FACTORY_SERVICE": "1",
        "HYDRAFLOW_FACTORY_WORKSPACE": str(workspace),
        "HYDRAFLOW_FACTORY_BRANCH": factory_branch,
        "HOME": str(home),
        "PATH": _service_path(home),
    }
    env_rows = "\n".join(
        f"        <key>{_esc(k)}</key>\n        <string>{_esc(v)}</string>"
        for k, v in environment.items()
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_esc(label)}</string>
    <key>ProgramArguments</key>
    <array>
{program_args_xml}
    </array>
    <key>WorkingDirectory</key>
    <string>{_esc(str(workspace))}</string>
    <key>EnvironmentVariables</key>
    <dict>
{env_rows}
    </dict>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>{_THROTTLE_INTERVAL_SECONDS}</integer>
    <key>StandardOutPath</key>
    <string>{_esc(str(stdout_path))}</string>
    <key>StandardErrorPath</key>
    <string>{_esc(str(stderr_path))}</string>
</dict>
</plist>
"""


def _launchctl_domain() -> str:
    return f"gui/{os.getuid()}"


def _run(cmd: list[str], *, dry_run: bool) -> subprocess.CompletedProcess[str] | None:
    if dry_run:
        logger.info("[dry-run] would run: %s", " ".join(cmd))
        return None
    return subprocess.run(  # noqa: S603
        cmd, check=False, capture_output=True, text=True, timeout=30
    )


def unload_if_loaded(plist_path: Path, *, dry_run: bool) -> None:
    """Best-effort ``launchctl bootout`` — a no-op if not currently loaded."""
    _run(
        ["launchctl", "bootout", _launchctl_domain(), str(plist_path)], dry_run=dry_run
    )


def load_agent(plist_path: Path, *, dry_run: bool) -> None:
    _run(
        ["launchctl", "bootstrap", _launchctl_domain(), str(plist_path)],
        dry_run=dry_run,
    )


def _dev_origin_url() -> str | None:
    """``origin`` of the checkout this installer runs from, or None."""
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "-C", str(_REPO_ROOT), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    url = (result.stdout or "").strip()
    return url or None


def _parse_knob(text: str) -> dict[str, str]:
    """``KEY=VALUE`` lines, blank lines / ``#`` comments ignored — the same
    grammar ``factory_liveness_watchdog.parse_knob_file`` reads."""
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def ensure_restart_label(knob_path: Path, *, label: str, dry_run: bool) -> None:
    """Give the liveness knob a restart target, without touching operator keys.

    * knob absent → create it with ``RESTART_ENABLED=true`` + ``RESTART_LABEL``;
    * knob has neither ``RESTART_COMMAND`` nor ``RESTART_LABEL`` (the state
      ``install_liveness_watchdog.py`` seeds) → append ``RESTART_LABEL``;
    * knob already names a command or label → leave it exactly as it is.
    """
    if not knob_path.exists():
        if dry_run:
            logger.info(
                "[dry-run] would create knob %s with RESTART_ENABLED=true "
                "RESTART_LABEL=%s",
                knob_path,
                label,
            )
            return
        knob_path.parent.mkdir(parents=True, exist_ok=True)
        knob_path.write_text(
            "# Auto-seeded by install_factory_service.py (ADR-0135).\n"
            "RESTART_ENABLED=true\n"
            f"RESTART_LABEL={label}\n",
            encoding="utf-8",
        )
        return
    text = knob_path.read_text(encoding="utf-8")
    knob = _parse_knob(text)
    if knob.get("RESTART_COMMAND", "").strip() or knob.get("RESTART_LABEL", "").strip():
        logger.info(
            "Knob %s already names a restart target — left untouched", knob_path
        )
        return
    if dry_run:
        logger.info("[dry-run] would append RESTART_LABEL=%s to %s", label, knob_path)
        return
    separator = "" if (not text or text.endswith("\n")) else "\n"
    knob_path.write_text(
        f"{text}{separator}"
        "# Restart target added by install_factory_service.py (ADR-0135).\n"
        f"RESTART_LABEL={label}\n",
        encoding="utf-8",
    )


def clone_workspace(workspace: Path, *, origin_url: str, dry_run: bool) -> None:
    """Clone the dev checkout's origin into ``workspace`` (interactive path only)."""
    if dry_run:
        logger.info("[dry-run] would clone %s -> %s", origin_url, workspace)
        return
    workspace.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Cloning %s -> %s", origin_url, workspace)
    subprocess.run(  # noqa: S603
        ["git", "clone", origin_url, str(workspace)], check=True, timeout=600
    )


def install(
    *,
    plist_path: Path,
    workspace: Path,
    factory_branch: str,
    home: Path,
    log_dir: Path,
    knob_path: Path,
    origin_url: str | None,
    dry_run: bool,
) -> None:
    if not (workspace / ".git").exists():
        if origin_url is not None:
            clone_workspace(workspace, origin_url=origin_url, dry_run=dry_run)
        elif dry_run:
            logger.info("[dry-run] would clone <unresolved origin> -> %s", workspace)
        else:
            raise RuntimeError(
                f"workspace {workspace} does not exist and this checkout has no "
                "readable 'origin' remote to clone it from"
            )

    xml = render_plist(
        label=_LABEL,
        workspace=workspace,
        factory_branch=factory_branch,
        home=home,
        stdout_path=log_dir / _STDOUT_NAME,
        stderr_path=log_dir / _STDERR_NAME,
    )

    if dry_run:
        logger.info("[dry-run] would write %s:\n%s", plist_path, xml)
    else:
        log_dir.mkdir(parents=True, exist_ok=True)
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        # Idempotent: unload any existing instance BEFORE overwriting, so a
        # re-install always ends with exactly one loaded agent reflecting the
        # freshly rendered plist.
        unload_if_loaded(plist_path, dry_run=False)
        plist_path.write_text(xml, encoding="utf-8")

    ensure_restart_label(knob_path, label=_LABEL, dry_run=dry_run)

    load_agent(plist_path, dry_run=dry_run)
    logger.info(
        "Installed %s -> %s (workspace %s, branch %s, KeepAlive)",
        _LABEL,
        plist_path,
        workspace,
        factory_branch,
    )


def uninstall(*, plist_path: Path, dry_run: bool) -> None:
    """Bootout + remove the plist. The liveness knob is deliberately left alone."""
    unload_if_loaded(plist_path, dry_run=dry_run)
    if dry_run:
        logger.info("[dry-run] would remove %s", plist_path)
    elif plist_path.exists():
        plist_path.unlink()
    logger.info("Uninstalled %s", _LABEL)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plist-path",
        type=Path,
        default=_DEFAULT_PLIST_PATH,
        help="Override the plist location (used by tests).",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=_DEFAULT_WORKSPACE,
        help="Dedicated factory workspace the service runs in place from. Must "
        "live under ~/.hydraflow/ (the launcher's service-mode invariant); "
        "cloned from this checkout's origin when absent.",
    )
    parser.add_argument(
        "--factory-branch",
        default=_DEFAULT_FACTORY_BRANCH,
        help="Branch the factory runs (ADR-0042: staging). Pinned into the plist "
        "EnvironmentVariables so the service never inherits a shell default.",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=_DEFAULT_LOG_DIR,
        help=f"Directory for {_STDOUT_NAME} / {_STDERR_NAME}.",
    )
    parser.add_argument(
        "--knob-path",
        type=Path,
        default=_DEFAULT_KNOB_PATH,
        help="Liveness restart knob; gains RESTART_LABEL=com.hydraflow.factory "
        "only when it names no restart target yet.",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Unload and remove the agent instead of installing it.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render/print intended actions without calling launchctl, cloning, "
        "or writing the plist/knob files.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = build_arg_parser().parse_args(argv)

    if not args.dry_run and platform.system() != "Darwin":
        logger.error(
            "This installer targets macOS launchd. On Linux, run "
            "scripts/run-factory-isolated.sh from a systemd unit instead "
            "(see docs/wiki/dependencies.md)."
        )
        return 1

    if args.uninstall:
        uninstall(plist_path=args.plist_path, dry_run=args.dry_run)
        return 0

    try:
        install(
            plist_path=args.plist_path,
            workspace=args.workspace,
            factory_branch=args.factory_branch,
            home=Path.home(),
            log_dir=args.log_dir,
            knob_path=args.knob_path,
            origin_url=_dev_origin_url(),
            dry_run=args.dry_run,
        )
    except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
        logger.error("Install failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
