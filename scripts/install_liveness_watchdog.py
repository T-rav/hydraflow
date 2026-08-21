#!/usr/bin/env python3
"""Install/uninstall the launchd agent for the external liveness watchdog (#10009).

Renders ``~/Library/LaunchAgents/com.hydraflow.liveness.plist`` pointing at
``scripts/factory_liveness_watchdog.py`` on a ``StartInterval`` of 300s (5
min), then (re)loads it via ``launchctl``. Idempotent: running install twice
just re-renders and reloads the same agent; ``--uninstall`` unloads and
removes it.

This is deliberately a manual, operator-run step — NOT something the factory
installs on itself. A factory loop cannot install the thing that watches for
the factory being down; see docs/wiki/dependencies.md.

Pair it with ``scripts/install_factory_service.py`` (ADR-0135), which runs the
factory itself as the ``com.hydraflow.factory`` launchd agent and gives the
``restart.knob`` seeded here its ``RESTART_LABEL`` target — without that label
``attempt_restart()`` has nothing to kick. Recipe (wiki "Factory-as-service
install recipe")::

    python scripts/install_factory_service.py
    python scripts/install_liveness_watchdog.py

Usage::

    scripts/install_liveness_watchdog.py                 # install/update
    scripts/install_liveness_watchdog.py --uninstall      # remove
    scripts/install_liveness_watchdog.py --dry-run        # render + print only

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

logger = logging.getLogger("install_liveness_watchdog")

_LABEL = "com.hydraflow.liveness"
_REPO_ROOT = Path(__file__).resolve().parent.parent
_WATCHDOG_SCRIPT = _REPO_ROOT / "scripts" / "factory_liveness_watchdog.py"
_DEFAULT_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{_LABEL}.plist"
_DEFAULT_LOG_DIR = Path.home() / ".hydraflow" / "liveness" / "logs"
_START_INTERVAL_SECONDS = 300
# Tier-1 boot-correctness kernel wiring (#10734).
_DEFAULT_WORKSPACE = Path.home() / ".hydraflow" / "factory-workspace" / "hydraflow"
_DEFAULT_FACTORY_BRANCH = "staging"
_DEFAULT_KNOB_PATH = Path.home() / ".hydraflow" / "liveness" / "restart.knob"


def render_plist(
    *,
    label: str,
    python_executable: str,
    watchdog_script: Path,
    extra_args: list[str],
    start_interval: int,
    stdout_path: Path,
    stderr_path: Path,
    environment: dict[str, str] | None = None,
) -> str:
    """Return the launchd plist XML as a string. Pure — no I/O.

    ``environment`` renders an ``EnvironmentVariables`` dict so the relaunched
    factory inherits the correct branch pin (``HYDRAFLOW_FACTORY_BRANCH=staging``)
    — without it, a launchd relaunch inherits the shell default ``main`` and
    boots stale (#10734).
    """

    def _esc(value: str) -> str:
        return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    args = [python_executable, str(watchdog_script), *extra_args]
    program_args_xml = "\n".join(f"        <string>{_esc(a)}</string>" for a in args)
    env_block = ""
    if environment:
        env_rows = "\n".join(
            f"        <key>{_esc(k)}</key>\n        <string>{_esc(v)}</string>"
            for k, v in environment.items()
        )
        env_block = f"""    <key>EnvironmentVariables</key>
    <dict>
{env_rows}
    </dict>
"""
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
{env_block}    <key>StartInterval</key>
    <integer>{start_interval}</integer>
    <key>RunAtLoad</key>
    <true/>
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
    domain = _launchctl_domain()
    _run(["launchctl", "bootout", domain, str(plist_path)], dry_run=dry_run)


def load_agent(plist_path: Path, *, dry_run: bool) -> None:
    domain = _launchctl_domain()
    _run(["launchctl", "bootstrap", domain, str(plist_path)], dry_run=dry_run)


def seed_restart_knob(knob_path: Path, *, dry_run: bool) -> None:
    """Seed ``restart.knob`` with ``RESTART_ENABLED=true`` only when absent.

    An existing knob is NEVER overwritten — the operator may have configured a
    custom ``RESTART_COMMAND``/``RESTART_LABEL`` that must survive re-install.
    """
    if knob_path.exists():
        return
    if dry_run:
        logger.info("[dry-run] would seed knob %s with RESTART_ENABLED=true", knob_path)
        return
    knob_path.parent.mkdir(parents=True, exist_ok=True)
    knob_path.write_text(
        "# Auto-seeded by install_liveness_watchdog.py (#10734).\n"
        "RESTART_ENABLED=true\n",
        encoding="utf-8",
    )


def install(
    *,
    plist_path: Path,
    log_dir: Path,
    extra_args: list[str],
    dry_run: bool,
    environment: dict[str, str] | None = None,
    knob_path: Path | None = None,
) -> None:
    if not dry_run:
        log_dir.mkdir(parents=True, exist_ok=True)
        plist_path.parent.mkdir(parents=True, exist_ok=True)

    xml = render_plist(
        label=_LABEL,
        python_executable=sys.executable,
        watchdog_script=_WATCHDOG_SCRIPT,
        extra_args=extra_args,
        start_interval=_START_INTERVAL_SECONDS,
        stdout_path=log_dir / "liveness.log",
        stderr_path=log_dir / "liveness.err.log",
        environment=environment,
    )

    if dry_run:
        logger.info("[dry-run] would write %s:\n%s", plist_path, xml)
    else:
        # Idempotent: unload any existing instance BEFORE overwriting, so a
        # re-install always ends with exactly one loaded agent reflecting
        # the freshly rendered plist (stale ProgramArguments never linger).
        unload_if_loaded(plist_path, dry_run=False)
        plist_path.write_text(xml, encoding="utf-8")

    if knob_path is not None:
        seed_restart_knob(knob_path, dry_run=dry_run)

    load_agent(plist_path, dry_run=dry_run)
    logger.info(
        "Installed %s -> %s (StartInterval=%ds)",
        _LABEL,
        plist_path,
        _START_INTERVAL_SECONDS,
    )


def uninstall(*, plist_path: Path, dry_run: bool) -> None:
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
        "--log-dir",
        type=Path,
        default=_DEFAULT_LOG_DIR,
    )
    parser.add_argument("--healthz-url", default=None)
    parser.add_argument("--events-path", default=None)
    parser.add_argument("--stale-seconds", default=None)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=_DEFAULT_WORKSPACE,
        help="Isolated factory workspace the watchdog guards for boot-correctness "
        "(#10734). Passed through as --workspace to the watchdog.",
    )
    parser.add_argument(
        "--factory-branch",
        default=_DEFAULT_FACTORY_BRANCH,
        help="Branch the factory must run on (ADR-0042: staging). Pinned into the "
        "plist EnvironmentVariables so a relaunch never inherits the shell "
        "default 'main'.",
    )
    parser.add_argument(
        "--knob-path",
        type=Path,
        default=_DEFAULT_KNOB_PATH,
        help="Restart knob seeded with RESTART_ENABLED=true only when absent.",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Unload and remove the agent instead of installing it.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render/print intended actions without calling launchctl or "
        "writing the plist file.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = build_arg_parser().parse_args(argv)

    if not args.dry_run and platform.system() != "Darwin":
        logger.error(
            "This installer targets macOS launchd. On Linux, run "
            "scripts/factory_liveness_watchdog.py from cron instead "
            "(see docs/wiki/dependencies.md)."
        )
        return 1

    if args.uninstall:
        uninstall(plist_path=args.plist_path, dry_run=args.dry_run)
        return 0

    extra_args: list[str] = []
    if args.healthz_url:
        extra_args += ["--healthz-url", args.healthz_url]
    if args.events_path:
        extra_args += ["--events-path", args.events_path]
    if args.stale_seconds:
        extra_args += ["--stale-seconds", str(args.stale_seconds)]
    # Wire the boot-correctness kernel: point the watchdog at the isolated
    # workspace and the branch it must stay pinned to (#10734).
    extra_args += ["--workspace", str(args.workspace)]
    extra_args += ["--factory-branch", args.factory_branch]

    install(
        plist_path=args.plist_path,
        log_dir=args.log_dir,
        extra_args=extra_args,
        dry_run=args.dry_run,
        environment={"HYDRAFLOW_FACTORY_BRANCH": args.factory_branch},
        knob_path=args.knob_path,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
