"""CorpusLearningLoop — grow the adversarial corpus from escape signals (§4.1 v2).

Phase 2 skeleton only: establishes the :class:`BaseBackgroundLoop` subclass,
its ``worker_name``, the injected dependencies (:class:`PRManager`,
:class:`DedupStore`, :class:`LoopDeps`), and the config-driven default
interval. The real tick body — escape-signal reader, in-process case
synthesis via ``BaseRunner._execute``, three-gate self-validation, and PR
filing against ``staging`` — lands in Tasks 11–14 of the
``2026-04-22-adversarial-skill-corpus`` plan.

Until then ``_do_work`` is a no-op: it honours the kill-switch
(``enabled_cb(worker_name)``) and returns a bare status dict so the base
class's :meth:`_execute_cycle` reporter has something to publish.

Kill-switch: :meth:`LoopDeps.enabled_cb` with ``worker_name="corpus_learning"``
— **no ``corpus_learning_enabled`` config field** (spec §12.2).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from models import WorkCycleResult  # noqa: TCH001

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager

logger = logging.getLogger("hydraflow.corpus_learning_loop")


class CorpusLearningLoop(BaseBackgroundLoop):
    """Grows ``tests/trust/adversarial/cases/`` from production escape signals.

    Skeleton (Phase 2 Task 9). Tick body will, across subsequent tasks:

    1. Query ``hydraflow-find`` issues labeled with the configured
       ``corpus_learning_signal_label`` (default ``skill-escape``).
    2. Synthesize a new case (``before/``, ``after/``,
       ``expected_catcher.txt``, ``README.md``) for each unseen issue via
       an in-process LLM call through ``BaseRunner._execute``.
    3. Self-validate the case (syntax, lint, trips the claimed catcher).
    4. Open a PR against ``staging`` that auto-merges through the standard
       reviewer + quality-gate path.

    On three self-validation failures for the same issue the loop labels
    it ``hitl-escalation`` + ``corpus-learning-stuck`` and moves on.
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

    async def _do_work(self) -> WorkCycleResult:
        """Tick the loop.

        The skeleton short-circuits with ``{"status": "disabled"}`` when
        the kill-switch is off and otherwise reports a noop with the
        stats shape that Tasks 11+ will populate. Keeping the ``noop``
        shape stable here avoids churning the status contract later.
        """
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        # Real synthesis lives in Tasks 11–14.
        return {
            "status": "noop",
            "escape_issues_seen": 0,
            "cases_proposed": 0,
            "escalated": 0,
        }
