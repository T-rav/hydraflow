"""CLI: install all Tier-1 + Tier-2 plugins declared in the active HydraFlow config.

Invoked by ``make install-plugins``. Reads the same config HydraFlow boots
with and runs ``claude plugin install`` for each missing plugin.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from config import HydraFlowConfig
from plugin_skill_registry import DEFAULT_CACHE_ROOT, parse_plugin_spec
from preflight import _plugin_exists

logger = logging.getLogger("hydraflow.install_plugins_cli")

_INSTALL_TIMEOUT_S = 120


def _install_plugin(
    name: str, marketplace: str, *, timeout_s: int = _INSTALL_TIMEOUT_S
) -> tuple[bool, str]:
    """Attempt ``claude plugin install name@marketplace --scope user``.

    Uses this module's ``subprocess.run`` so tests can patch it via
    ``patch("install_plugins_cli.subprocess.run", ...)``.

    Returns ``(success, detail)`` where ``detail`` is the tail of stderr
    (or a human-readable error string) for logging.
    """
    argv = [
        "claude",
        "plugin",
        "install",
        f"{name}@{marketplace}",
        "--scope",
        "user",
    ]
    try:
        result = subprocess.run(  # noqa: S603
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError:
        return False, "`claude` binary not found on PATH"
    except subprocess.TimeoutExpired:
        return False, f"install timed out after {timeout_s}s"

    if result.returncode == 0:
        return True, result.stdout.strip()
    return False, (result.stderr or result.stdout or "non-zero exit").strip()


def run(config: HydraFlowConfig, *, cache_root: Path | None = None) -> int:
    """Install every plugin in ``config`` not yet present in ``cache_root``.

    Returns process exit code: 0 on success, non-zero if any install failed.
    """
    root = cache_root or DEFAULT_CACHE_ROOT
    all_entries = list(config.required_plugins)
    for plugins in config.language_plugins.values():
        all_entries.extend(plugins)

    failures: list[str] = []
    for entry in all_entries:
        try:
            name, marketplace = parse_plugin_spec(entry)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        if _plugin_exists(root, name):
            logger.info("already installed: %s@%s", name, marketplace)
            continue
        ok, detail = _install_plugin(name, marketplace)
        if ok:
            logger.info("installed %s@%s", name, marketplace)
        else:
            failures.append(f"{name}@{marketplace}: {detail}")

    if failures:
        for f in failures:
            logger.error(f)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m install_plugins_cli``."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = HydraFlowConfig()  # defaults; no CLI args — matches make target expectations
    return run(cfg)


if __name__ == "__main__":
    sys.exit(main())
