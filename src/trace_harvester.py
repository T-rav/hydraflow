"""Harvest Monocle trace files from worktrees before cleanup."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger("hydraflow.trace_harvester")


def harvest_traces(
    worktree_path: Path,
    *,
    issue_number: int,
    phase: str,
    data_path: Path,
) -> int:
    """Copy .monocle trace files to durable storage before worktree destroy.

    Returns the number of files harvested (0 if none found).
    """
    monocle_dir = worktree_path / ".monocle"
    if not monocle_dir.is_dir():
        return 0

    trace_files = list(monocle_dir.glob("monocle_trace_*.json"))
    if not trace_files:
        return 0

    raw_dir = data_path / "traces" / str(issue_number) / phase / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    for src in trace_files:
        shutil.copy2(src, raw_dir / src.name)

    logger.info(
        "Harvested %d trace files for issue #%d (%s)",
        len(trace_files),
        issue_number,
        phase,
    )
    return len(trace_files)
