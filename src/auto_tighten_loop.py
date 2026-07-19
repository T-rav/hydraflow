"""AutoTightenLoop — caretaker loop for the auto-tighten ratchet.

Ties together the pieces built across Tasks 2-11: per-tick it ingests the
latest CI coverage (``CoverageIngestor``), asks each ``RatchetAdapter`` for
its current/baseline measurement, classifies the direction
(``TighteningEngine.classify``), records an ``Observation``, and — once a
tightening direction has held stable for ``auto_tighten_stability_ticks``
consecutive ticks (``TighteningEngine.confirm``) — attributes the gain to a
recently-merged PR (``AttributionResolver``) before opening an automated PR
that raises the floor (``TighteningPrAuthor``).

Unattributed gains safely HOLD: no PR is opened, and no exception is raised.
Attribution is a confidence gate, not a correctness guard — the monotone
safety property (never actuate a non-tightening value) is enforced
separately by ``TighteningEngine.guard_is_tighter`` immediately before
rendering the edit.

The loop is registered in the service registry, orchestrator, dashboard, and
scenario catalog (Task 13); it is off by default via
``auto_tighten_loop_enabled``.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from auto_tighten.attribution import baseline_since
from auto_tighten.engine import TighteningEngine
from auto_tighten.models import ConfirmedTightening, Measurement, Observation
from base_background_loop import BaseBackgroundLoop, LoopDeps
from events import EventType, HydraFlowEvent
from loop_fitness import FitnessContext, FitnessKind, LoopFitness

if TYPE_CHECKING:
    from auto_tighten.attribution import AttributionResolver
    from auto_tighten.coverage_ingestor import CoverageIngestor
    from auto_tighten.observation_store import ObservationStore
    from auto_tighten.pr_author import TighteningPrAuthor
    from auto_tighten.ratchet_adapter import RatchetAdapter
    from config import HydraFlowConfig
    from models import WorkCycleResult
    from state import StateTracker

logger = logging.getLogger("hydraflow.auto_tighten_loop")

# Paths of interest for attributing a tightening gain to a merged PR — a
# coverage rise is credited to the most recent merged PR that touched test
# or source code, since that's what would plausibly move coverage.
_ATTRIBUTION_PATHS = ("tests/", "src/")


class AutoTightenLoop(BaseBackgroundLoop):
    """Auto-tightening ratchet caretaker loop.

    Read-write surface: opens automated PRs via ``TighteningPrAuthor`` (which
    itself writes the rendered file edits) plus appends to the
    ``ObservationStore``'s jsonl. It never edits repo source directly — all
    file edits are produced by ``RatchetAdapter.render_tightened`` and
    applied by the PR author as part of opening the PR.
    """

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        deps: LoopDeps,
        adapters: list[RatchetAdapter],
        ingestor: CoverageIngestor,
        attribution: AttributionResolver,
        pr_author: TighteningPrAuthor,
        observation_store: ObservationStore,
    ) -> None:
        super().__init__(
            worker_name="auto_tighten",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._adapters = adapters
        self._ingestor = ingestor
        self._attribution = attribution
        self._pr_author = pr_author
        self._obs = observation_store
        self._engine = TighteningEngine()
        self._repo_root = config.repo_root

    def _get_default_interval(self) -> int:
        return self._config.auto_tighten_interval

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        # Read-only-of-ADRs, write-via-PR maintenance loop; no
        # proposal/acceptance lifecycle of its own to score — HOUSEKEEPING
        # per ADR-0093's fitness contract. Mirrors AdrConformanceLoop.
        return LoopFitness(
            worker_name=self._worker_name,
            kind=FitnessKind.HOUSEKEEPING,
            timestamp=ctx.window_end,
        )

    async def _emit_tightened(
        self, ratchet_id: str, floor: Measurement, pr_url: str
    ) -> None:
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.RATCHET_TIGHTENED,
                data={
                    "ratchet_id": ratchet_id,
                    "floor": floor,
                    "pr_url": pr_url,
                },
            )
        )

    async def _emit_unattributed(self, ratchet_id: str, floor: Measurement) -> None:
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.RATCHET_TIGHTENED,
                data={
                    "ratchet_id": ratchet_id,
                    "floor": floor,
                    "unattributed": True,
                },
            )
        )

    def _baseline_since(self, adapter: RatchetAdapter) -> str:
        """Resolve the attribution scan's lower-bound timestamp.

        Coverage is the only adapter shipped so far, and its baseline lives
        in pyproject.toml's ``fail_under``; other adapters may not have a
        single baseline file, so default conservatively to the fallback
        window when the adapter doesn't declare one.
        """
        rel_path = getattr(adapter, "baseline_path", "pyproject.toml")
        return baseline_since(self._repo_root, rel_path)

    async def _do_work(self) -> WorkCycleResult:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.auto_tighten_loop_enabled:
            return {"status": "config_disabled"}

        t0 = time.perf_counter()
        self._ingestor.ingest()

        now = datetime.now(UTC).isoformat()
        tightened = 0
        held = 0
        for adapter in self._adapters:
            try:
                current = adapter.current(self._repo_root)
            except FileNotFoundError:
                continue  # no data yet (cold start)
            baseline = adapter.baseline(self._repo_root)
            direction = self._engine.classify(adapter, current, baseline)
            self._obs.append(
                Observation(
                    ts=now,
                    ratchet_id=adapter.ratchet_id,
                    current=current,
                    baseline=baseline,
                    direction=direction,
                )
            )
            if direction != "tighter":
                continue

            window = self._obs.window(
                adapter.ratchet_id, limit=self._config.auto_tighten_stability_ticks
            )
            floor = self._engine.confirm(
                adapter, window, baseline, self._config.auto_tighten_stability_ticks
            )
            if floor is None:
                continue

            pr_num = self._attribution.attribute(
                list(_ATTRIBUTION_PATHS), since_iso=self._baseline_since(adapter)
            )
            if pr_num is None:
                await self._emit_unattributed(adapter.ratchet_id, floor)
                held += 1
                continue

            # Safety: raises if the confirmed floor somehow isn't tighter
            # than baseline — must never actuate a non-tightening value.
            self._engine.guard_is_tighter(adapter, floor, baseline)
            edits = adapter.render_tightened(self._repo_root, floor)
            ct = ConfirmedTightening(
                ratchet_id=adapter.ratchet_id,
                floor=floor,
                file_edits=edits,
                dedup_key=adapter.dedup_key(floor),
                evidence=f"PR #{pr_num}",
            )
            url = await self._pr_author.open(ct)
            if url:
                tightened += 1
                await self._emit_tightened(adapter.ratchet_id, floor, url)

        self._emit_trace(t0, tightened=tightened, held=held)
        return {"status": "ok", "tightened": tightened, "held": held}

    def _emit_trace(self, t0: float, *, tightened: int, held: int) -> None:
        try:
            from trace_collector import emit_loop_subprocess_trace  # noqa: PLC0415
        except ImportError:
            return
        duration_ms = int((time.perf_counter() - t0) * 1000)
        emit_loop_subprocess_trace(
            loop=self._worker_name,
            command=["auto_tighten", "tick"],
            exit_code=0,
            duration_ms=duration_ms,
            stderr_excerpt=f"tightened={tightened} held={held}",
        )
