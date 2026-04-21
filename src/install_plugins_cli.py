"""CLI: install all Tier-1 + Tier-2 plugins declared in the active HydraFlow config.

Invoked by ``make install-plugins``. Reads the same config HydraFlow boots
with and runs ``claude plugin install`` for each missing plugin via the
shared :func:`preflight.install_plugin` helper.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from config import HydraFlowConfig
from plugin_skill_registry import DEFAULT_CACHE_ROOT, parse_plugin_spec
from preflight import install_plugin, plugin_exists

logger = logging.getLogger("hydraflow.install_plugins_cli")


def run(config: HydraFlowConfig, *, cache_root: Path | None = None) -> int:
    """Install every plugin in ``config`` not yet present in ``cache_root``.

    Returns 0 on success or when only Tier-2 (language-conditional) plugins
    fail; returns 1 if any Tier-1 (``required_plugins``) plugin fails.
    Mirrors preflight's Tier-1 FAIL / Tier-2 WARN distinction.
    """
    root = cache_root or DEFAULT_CACHE_ROOT

    tier2_entries: list[str] = []
    for plugins in config.language_plugins.values():
        tier2_entries.extend(plugins)

    tier1_failures = _install_tier(list(config.required_plugins), root)
    tier2_failures = _install_tier(tier2_entries, root)

    for failure in tier1_failures:
        logger.error("%s", failure)
    for failure in tier2_failures:
        logger.warning("%s", failure)

    return 1 if tier1_failures else 0


def _install_tier(entries: list[str], root: Path) -> list[str]:
    """Install every entry in ``entries`` not yet present in ``root``.

    Returns a list of ``"name@marketplace: detail"`` strings for each
    entry that failed to parse or install. Already-installed plugins are
    logged at INFO and omitted from the failures list.
    """
    failures: list[str] = []
    for entry in entries:
        try:
            name, marketplace = parse_plugin_spec(entry)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        if plugin_exists(root, name):
            logger.info("already installed: %s@%s", name, marketplace)
            continue
        ok, detail = install_plugin(name, marketplace)
        if ok:
            logger.info("installed %s@%s", name, marketplace)
        else:
            failures.append(f"{name}@{marketplace}: {detail}")
    return failures


def main() -> int:
    """Entry point for ``python -m install_plugins_cli``."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = HydraFlowConfig()  # defaults; no CLI args — matches make target expectations
    return run(cfg)


if __name__ == "__main__":
    sys.exit(main())
