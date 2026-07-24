"""Boot-time local-branch unpushed-work detector (#10011 part 2).

A finished fix can sit committed on a local branch, genuinely done, and
still be invisible to the rest of the factory because nothing ever pushed
it — the exact shape hit by the regression-collection fix (later PR #9965),
which sat committed-but-unpushed on a local branch overnight. Nothing in
the boot path scanned local git state to catch this.

:func:`check_and_alert_unpushed_branches` runs once per repo-runtime boot
(:meth:`repo_runtime.RepoRuntime.create`, and explicitly for the
dashboard-mode host runtime in ``server.py`` since that path reuses an
already-built runtime via ``from_shared`` rather than ``create``). It is a
single ``git for-each-ref`` call — no network, no GitHub API — comparing
each local branch's tip to its own upstream tracking ref. Any branch ahead
of its upstream logs one loud ``WARNING`` and the whole finding set is
published as ONE ``SYSTEM_ALERT`` so the dashboard can surface it; a clean
scan is a silent no-op.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from branch_gc_scan import UnpushedBranch, parse_unpushed_branches
from events import EventType, HydraFlowEvent
from subprocess_util import run_subprocess

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from events import EventBus

logger = logging.getLogger("hydraflow.unpushed_branch_alert")

_FOR_EACH_REF_FORMAT = "%(refname:short)|%(upstream:short)|%(upstream:track)"


async def scan_unpushed_local_branches(repo_root: Path) -> list[UnpushedBranch]:
    """Scan *repo_root* for local branches ahead of their own upstream.

    Purely local — no network. Returns ``[]`` (never raises) when
    *repo_root* isn't a git checkout or the scan otherwise fails; a boot
    check must never abort startup.
    """
    try:
        raw = await run_subprocess(
            "git",
            "for-each-ref",
            f"--format={_FOR_EACH_REF_FORMAT}",
            "refs/heads/",
            cwd=repo_root,
        )
    except (RuntimeError, OSError):
        logger.debug(
            "Could not scan %s for unpushed local branches", repo_root, exc_info=True
        )
        return []
    return parse_unpushed_branches(raw)


async def check_and_alert_unpushed_branches(
    config: HydraFlowConfig, event_bus: EventBus | None
) -> list[UnpushedBranch]:
    """Scan for committed-but-unpushed local branches; log + alert once if any.

    Publish/log failures never raise — a broken boot check must not abort
    startup.
    """
    branches = await scan_unpushed_local_branches(config.repo_root)
    if not branches:
        return branches

    detail = "; ".join(f"{b.branch} (+{b.ahead} vs {b.upstream})" for b in branches)
    logger.warning(
        "Boot check: %d local branch(es) have committed-but-unpushed work — "
        "this work is invisible to the factory until pushed: %s",
        len(branches),
        detail,
    )

    if event_bus is not None:
        try:
            await event_bus.publish(
                HydraFlowEvent(
                    type=EventType.SYSTEM_ALERT,
                    data={
                        "kind": "unpushed_local_branches",
                        "branches": [b.branch for b in branches],
                        "detail": detail,
                        # `message` is the field the dashboard banner renders
                        # (SystemAlertPayload); `severity` keeps this benign,
                        # informational condition yellow instead of the red
                        # default (#10486).
                        "message": (
                            f"{len(branches)} local branch(es) have "
                            "committed-but-unpushed work (invisible to the "
                            f"factory until pushed): {detail}"
                        ),
                        "severity": "warning",
                    },
                )
            )
        except Exception:
            logger.warning(
                "SYSTEM_ALERT publish failed for unpushed local branches",
                exc_info=True,
            )

    return branches
