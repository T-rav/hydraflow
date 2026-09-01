"""Post-merge retrospective analysis for the HydraFlow orchestrator."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from exception_classify import reraise_on_credit_or_bug
from models import IsoTimestamp, PlanAccuracyResult, ReviewVerdict
from retro_emitter import emit
from retro_evidence import gather
from retro_finder import RetroFinder
from retro_findings import validate
from retro_signals import extract

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from models import ReviewResult
    from ports import ObservabilityPort
    from pr_manager import PRManager
    from retrospective_queue import RetrospectiveQueue
    from state import StateTracker

logger = logging.getLogger("hydraflow.retrospective")


class RetrospectiveEntry(BaseModel):
    """A single retrospective record appended to the JSONL log."""

    issue_number: int
    pr_number: int
    timestamp: IsoTimestamp
    plan_accuracy_pct: float = 0.0
    planned_files: list[str] = Field(default_factory=list)
    actual_files: list[str] = Field(default_factory=list)
    unplanned_files: list[str] = Field(default_factory=list)
    missed_files: list[str] = Field(default_factory=list)
    quality_fix_rounds: int = 0
    review_verdict: ReviewVerdict | Literal[""] = ""
    reviewer_fixes_made: bool = False
    ci_fix_rounds: int = 0
    duration_seconds: float = 0.0


class RetrospectiveCollector:
    """Collects post-merge retrospective data and detects patterns."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        prs: PRManager,
        *,
        queue: RetrospectiveQueue | None = None,
        observability: ObservabilityPort | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._prs = prs
        self._queue = queue
        self._obs: ObservabilityPort | None = observability
        self._retro_path = config.retrospectives_path
        self._finder = RetroFinder(config)

    async def record(
        self,
        issue_number: int,
        pr_number: int,
        review_result: ReviewResult,
    ) -> None:
        """Run the full retrospective: collect, store, detect patterns.

        This method is designed to be non-blocking — exceptions are
        caught and logged so they never interrupt the merge flow.
        """
        try:
            entry = await self._collect(issue_number, pr_number, review_result)
            self._append_entry(entry)
            if self._obs is not None:
                self._obs.breadcrumb(
                    "retrospective.stored",
                    f"Retrospective stored for issue #{issue_number}",
                    level="info",
                    issue_number=issue_number,
                    accuracy=entry.plan_accuracy_pct,
                )
            if self._queue is not None:
                from retrospective_queue import QueueItem, QueueKind  # noqa: PLC0415

                self._queue.append(
                    QueueItem(
                        kind=QueueKind.RETRO_PATTERNS,
                        issue_number=issue_number,
                    )
                )
            else:
                # Fallback: inline analysis when the queue is not wired.
                await self.analyze_evidence(
                    self._load_recent(self._config.retrospective_window)
                )
        except Exception:
            logger.warning(
                "Retrospective failed for issue #%d — continuing",
                issue_number,
                exc_info=True,
            )

    async def _collect(
        self,
        issue_number: int,
        pr_number: int,
        review_result: ReviewResult,
    ) -> RetrospectiveEntry:
        """Gather all data and build a RetrospectiveEntry."""
        plan_text = self._read_plan_file(issue_number)
        planned_files = self._parse_planned_files(plan_text)
        actual_files = await self._get_actual_files(pr_number)
        accuracy, unplanned, missed = self._compute_accuracy(
            planned_files, actual_files
        )

        meta = self._state.get_worker_result_meta(issue_number)
        led = self._state.get_convergence_ledger(issue_number)
        quality_fix_rounds = led.get_attempts("quality_fix") if led else 0
        impl_duration = meta.get("duration_seconds", 0.0)

        return RetrospectiveEntry(
            issue_number=issue_number,
            pr_number=pr_number,
            timestamp=datetime.now(UTC).isoformat(),
            plan_accuracy_pct=accuracy,
            planned_files=planned_files,
            actual_files=actual_files,
            unplanned_files=unplanned,
            missed_files=missed,
            quality_fix_rounds=quality_fix_rounds,
            review_verdict=review_result.verdict,
            reviewer_fixes_made=review_result.fixes_made,
            ci_fix_rounds=review_result.ci_fix_attempts,
            duration_seconds=impl_duration,
        )

    def _read_plan_file(self, issue_number: int) -> str:
        """Read the plan file for *issue_number*, returning empty string on failure."""
        plan_path = self._config.data_path("plans", f"issue-{issue_number}.md")
        try:
            return plan_path.read_text()
        except OSError:
            logger.debug("Plan file not found for issue #%d", issue_number)
            return ""

    def _parse_planned_files(self, plan_text: str) -> list[str]:
        """Extract file paths from plan text.

        Prefers the structured ``## File Delta`` section if present,
        falling back to heuristic extraction from ``## Files to Modify``
        and ``## New Files``.
        """
        if not plan_text:
            return []

        # Try structured delta first
        from delta_verifier import parse_file_delta

        delta_files = parse_file_delta(plan_text)
        if delta_files:
            return delta_files

        # Fallback: heuristic extraction from prose sections
        files: list[str] = []
        in_section = False

        for line in plan_text.splitlines():
            stripped = line.strip()

            # Detect start of relevant sections
            if re.match(r"^##\s+(Files to Modify|New Files)", stripped):
                in_section = True
                continue

            # End section on next heading
            if in_section and re.match(r"^##\s+", stripped):
                in_section = False
                continue

            if not in_section:
                continue

            # Extract file paths from list items:
            #   - `src/foo.py`
            #   - **src/foo.py**
            #   - src/foo.py
            #   ### 1. `src/foo.py` (NEW)
            # Match backtick-delimited paths
            backtick_matches = re.findall(r"`([^`]+\.\w+)`", stripped)
            if backtick_matches:
                files.extend(backtick_matches)
                continue

            # Match bold paths: **path/to/file.py**
            bold_matches = re.findall(r"\*\*([^*]+\.\w+)\*\*", stripped)
            if bold_matches:
                files.extend(bold_matches)
                continue

            # Match bare paths on list items: - path/to/file.py
            bare_match = re.match(r"^[-*]\s+(\S+\.\w+)", stripped)
            if bare_match:
                files.append(bare_match.group(1))

        return sorted(set(files))

    async def _get_actual_files(self, pr_number: int) -> list[str]:
        return await self._prs.get_pr_diff_names(pr_number)

    @staticmethod
    def _compute_accuracy(planned: list[str], actual: list[str]) -> PlanAccuracyResult:
        """Compute plan accuracy percentage, unplanned files, and missed files."""
        planned_set = set(planned)
        actual_set = set(actual)
        unplanned = sorted(actual_set - planned_set)
        missed = sorted(planned_set - actual_set)
        intersection = planned_set & actual_set

        if not planned_set:
            accuracy = 0.0
        else:
            accuracy = round(len(intersection) / len(planned_set) * 100, 1)

        return PlanAccuracyResult(accuracy=accuracy, unplanned=unplanned, missed=missed)

    def _append_entry(self, entry: RetrospectiveEntry) -> None:
        """Append a JSON line to the retrospective log."""
        try:
            from file_util import append_jsonl  # noqa: PLC0415

            append_jsonl(self._retro_path, entry.model_dump_json())
        except OSError:
            logger.warning(
                "Could not append to retrospective log %s",
                self._retro_path,
                exc_info=True,
            )

    def _load_recent(self, n: int) -> list[RetrospectiveEntry]:
        """Load the last *n* entries from the retrospective log."""
        if not self._retro_path.exists():
            return []
        try:
            lines = self._retro_path.read_text().strip().splitlines()
            entries: list[RetrospectiveEntry] = []
            for line in lines[-n:]:
                if line.strip():
                    entries.append(RetrospectiveEntry.model_validate_json(line))
            return entries
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not load retrospective log", exc_info=True)
            return []

    async def analyze_evidence(
        self, entries: list[RetrospectiveEntry]
    ) -> dict[str, int]:
        """Turn recent issues' traces and transcripts into filed findings.

        Replaces the four hardcoded prose branches this class used to emit —
        "consider strengthening the implementation prompt" and friends — none
        of which could name a file, a command, an error or a guard, because
        ``RetrospectiveEntry`` carries no field that could hold one.
        """
        counts = {
            "signals": 0,
            "filed": 0,
            "policy": 0,
            "dropped": 0,
            "errors": 0,
            "unparseable": 0,
            "capped": 0,
        }
        issues = sorted({e.issue_number for e in entries})
        if not issues:
            return counts

        signals = extract([gather(self._config, n) for n in issues])
        counts["signals"] = len(signals)
        if not signals:
            return counts

        # Label lookup is one API call per issue in the window; skip it
        # entirely when the finder will not spawn.
        labels = (
            await self._window_labels(issues)
            if self._config.retro_finder_enabled
            else []
        )
        findings = await self._finder.find(signals, issue_labels=labels)
        counts["unparseable"] = getattr(self._finder, "unparseable", 0)
        kept, dropped = validate(findings, signals, Path(self._config.repo_root))
        # Both kinds of loss, in the one number a caller reads. `unparseable`
        # counts items the finder could not turn into a Finding at all
        # (#11903); `dropped` counted only the ones that parsed and then failed
        # `validate`. It was computed and surfaced nowhere, so a tick that
        # confabulated every item reported `findings_dropped: 0` — indis-
        # tinguishable from a clean tick, which is the #11965 audit escape.
        # The breakdown stays available as `counts["unparseable"]`.
        counts["dropped"] = len(dropped) + counts["unparseable"]
        for drop in dropped:
            logger.info("Retro finding dropped (%s): %s", drop.kind, drop.reason)

        counts.update(await emit(kept, signals, self._prs, self._config))
        return counts

    async def _window_labels(self, issues: list[int]) -> list[str]:
        """Union of labels across the issues whose evidence was read.

        The finder reads many issues at once, so CH-6's upward-only
        ``data-class:`` elevation must see all of them, not any single one. A
        lookup failure degrades to no labels rather than sinking the analysis.
        """
        labels: set[str] = set()
        for number in issues:
            try:
                labels.update(await self._prs.get_issue_labels(number))
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.debug("Could not read labels for #%d: %s", number, exc)
        return sorted(labels)
