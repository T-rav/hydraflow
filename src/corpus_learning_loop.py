"""CorpusLearningLoop — grow the adversarial corpus from escape signals (§4.1 v2).

Phase 2 Task 11 — escape-signal reader wired in. The loop now queries
``PRManager.list_issues_by_label`` for open issues tagged with the
configured escape label (default :data:`DEFAULT_ESCAPE_LABEL`), filters
to the last :data:`DEFAULT_LOOKBACK_DAYS` days, and materializes each
row into an :class:`EscapeSignal` dataclass. Subsequent tasks (12–14)
will synthesize corpus cases from these signals, self-validate them,
and open PRs against ``staging``; Task 15 surfaces the label + lookback
as runtime-tunable config fields.

Kill-switch: :meth:`LoopDeps.enabled_cb` with ``worker_name="corpus_learning"``
— **no ``corpus_learning_enabled`` config field** (spec §12.2).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from models import WorkCycleResult  # noqa: TCH001

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager

logger = logging.getLogger("hydraflow.corpus_learning_loop")

#: Default GitHub label that marks an issue as a production escape
#: signal. Task 15 will surface this as a
#: ``corpus_learning_signal_label`` config field; until then callers and
#: tests can override via the ``label`` parameter on
#: :meth:`CorpusLearningLoop._list_escape_signals`.
DEFAULT_ESCAPE_LABEL = "skill-escape"

#: Default recency window (days) for escape signals. Issues whose
#: ``updated_at`` is older than this are dropped from the reader so the
#: synthesizer focuses on live regressions, not archived noise.
DEFAULT_LOOKBACK_DAYS = 30


@dataclass(frozen=True, slots=True)
class EscapeSignal:
    """A parsed escape-signal row from a ``skill-escape``-labeled issue.

    Intentionally narrow: carries just the fields Task 12's synthesizer
    needs (``issue_number``, ``title``, ``body``) plus the provenance
    bits (``updated_at``, ``label``) the loop uses for filtering and
    telemetry. Reading new GitHub fields means extending this shape —
    never stashing raw ``dict`` rows downstream.
    """

    issue_number: int
    title: str
    body: str
    updated_at: str
    label: str


class CorpusLearningLoop(BaseBackgroundLoop):
    """Grows ``tests/trust/adversarial/cases/`` from production escape signals.

    Current state (Task 11): the escape-signal reader is wired in.
    ``_do_work`` fetches escape signals when enabled and reports the
    count; synthesis, self-validation, and PR filing land in
    Tasks 12–14.

    On three self-validation failures for the same issue the loop will
    (Task 13) label it ``hitl-escalation`` + ``corpus-learning-stuck``
    and move on.
    """

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        prs: PRManager,
        dedup: DedupStore,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="corpus_learning",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._prs = prs
        self._dedup = dedup

    def _get_default_interval(self) -> int:
        return self._config.corpus_learning_interval

    async def _list_escape_signals(
        self,
        *,
        label: str = DEFAULT_ESCAPE_LABEL,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    ) -> list[EscapeSignal]:
        """Return escape-signal issues labeled ``label`` from the last ``lookback_days``.

        Delegates to :meth:`PRManager.list_issues_by_label` (the
        canonical ``gh issue list`` wrapper) so CI-mocked and
        scenario-mocked runs stay on a single seam. Rows without a
        usable ``number`` or with an unparseable ``updated_at`` are
        dropped — better to skip a malformed row than poison Task 12's
        synthesizer with ``issue_number=0`` or a ``None`` timestamp.
        """
        raw_issues = await self._prs.list_issues_by_label(label)
        if not raw_issues:
            return []

        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        signals: list[EscapeSignal] = []
        for row in raw_issues:
            issue_number = row.get("number", 0)
            if not issue_number:
                continue
            updated_at_raw = row.get("updated_at", "") or ""
            parsed = _parse_iso_timestamp(updated_at_raw)
            if parsed is None:
                logger.debug(
                    "corpus-learning: dropping issue #%d with unparseable updated_at=%r",
                    issue_number,
                    updated_at_raw,
                )
                continue
            if parsed < cutoff:
                continue
            signals.append(
                EscapeSignal(
                    issue_number=issue_number,
                    title=row.get("title", "") or "",
                    body=row.get("body", "") or "",
                    updated_at=updated_at_raw,
                    label=label,
                )
            )
        return signals

    async def _do_work(self) -> WorkCycleResult:
        """Tick the loop.

        When the kill-switch is off, short-circuits with
        ``{"status": "disabled"}``. Otherwise fetches escape signals and
        reports the count; Tasks 12–14 will populate ``cases_proposed``
        and ``escalated`` as synthesis + validation come online.
        """
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        signals = await self._list_escape_signals()
        if signals:
            logger.info(
                "corpus-learning: %d escape signal(s) within %d-day window",
                len(signals),
                DEFAULT_LOOKBACK_DAYS,
            )

        return {
            "status": "noop",
            "escape_issues_seen": len(signals),
            "cases_proposed": 0,
            "escalated": 0,
        }


def _parse_iso_timestamp(value: str) -> datetime | None:
    """Parse a GitHub-style ISO-8601 timestamp, returning ``None`` on failure.

    GitHub returns ``updated_at`` as e.g. ``"2026-04-22T14:05:00Z"``.
    :meth:`datetime.fromisoformat` accepts ``+00:00`` natively but only
    accepts the trailing ``Z`` since Python 3.11 — we normalize it
    explicitly so the intent is obvious and the parser never surprises
    a reader hunting a ``ValueError``.
    """
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
