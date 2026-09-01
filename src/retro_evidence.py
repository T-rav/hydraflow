"""Pure evidence gathering for the retrospective.

The pipeline already writes everything a retro needs: `SubprocessTrace` JSONs
under ``<data_root>/traces/<issue>/<phase>/run-<N>/`` and phase transcripts
under ``<log_dir>/``. Nothing here writes, spawns, or calls out — gathering
must never be the reason a retro tick fails, and a repo predating trace
collection simply yields an empty bundle.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, ValidationError

from models import SubprocessTrace

if TYPE_CHECKING:
    from pathlib import Path

    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.retro_evidence")

# Cap on how much of ONE transcript is held in memory. Agent transcripts run to
# megabytes and a tick gathers `retrospective_window` issues' worth, so an
# unbounded read is a background loop holding the whole window at once. The
# TAIL is kept for the same reason transcript_summarizer keeps it: failures and
# final decisions land at the end.
MAX_TRANSCRIPT_CHARS = 40_000

# Transcript filenames keyed by ISSUE number. `review-pr` / `review-fix` are
# deliberately absent: reviewer/_fixes.py keys those by PR number, a different
# entity. Coverage of this tuple against the live `_save_transcript` call sites
# is derived, not restated, in tests/test_retro_evidence.py.
TRANSCRIPT_GLOBS: tuple[str, ...] = (
    "issue-{n}.txt",
    "plan-issue-{n}.txt",
    "triage-issue-{n}.txt",
    "hitl-issue-{n}.txt",
    "research-issue-{n}.txt",
    "discover-issue-attempt*-{n}.txt",
    "shape-issue-turn*-attempt*-{n}.txt",
)


class RetroEvidence(BaseModel):
    """Everything on disk about one issue's pipeline run."""

    issue_number: int
    traces: list[SubprocessTrace] = Field(default_factory=list)
    transcripts: dict[str, str] = Field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.traces and not self.transcripts


def gather(config: HydraFlowConfig, issue_number: int) -> RetroEvidence:
    """Read one issue's traces and transcripts. Never raises."""
    return RetroEvidence(
        issue_number=issue_number,
        traces=_load_traces(config.data_root / "traces" / str(issue_number)),
        transcripts=_load_transcripts(config.log_dir, issue_number),
    )


def _load_traces(issue_dir: Path) -> list[SubprocessTrace]:
    if not issue_dir.is_dir():
        return []
    traces: list[SubprocessTrace] = []
    for path in sorted(issue_dir.glob("*/run-*/subprocess-*.json")):
        try:
            traces.append(
                SubprocessTrace.model_validate_json(path.read_text(encoding="utf-8"))
            )
        except (OSError, ValidationError, ValueError):
            logger.debug("Skipping malformed subprocess trace: %s", path)
    return traces


def _read_tail(path: Path) -> str:
    """Read at most ``MAX_TRANSCRIPT_CHARS`` from the END of *path*."""
    size = path.stat().st_size
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        if size > MAX_TRANSCRIPT_CHARS:
            handle.seek(max(0, size - MAX_TRANSCRIPT_CHARS))
        return handle.read()[-MAX_TRANSCRIPT_CHARS:]


def _load_transcripts(log_dir: Path, issue_number: int) -> dict[str, str]:
    if not log_dir.is_dir():
        return {}
    transcripts: dict[str, str] = {}
    for template in TRANSCRIPT_GLOBS:
        for path in sorted(log_dir.glob(template.format(n=issue_number))):
            try:
                transcripts[path.stem] = _read_tail(path)
            except OSError:
                logger.debug("Could not read transcript: %s", path)
    return transcripts
