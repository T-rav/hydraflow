"""Read-only caretaker loop that computes per-loop fitness (ADR-0029 shape).

Builds one pure FitnessContext per tick and calls every registered loop's
loop_fitness. Persists to fitness.jsonl, regenerates
docs/arch/generated/loop-fitness.md, and emits LOOP_FITNESS_UPDATE. Mutates no
loop state -- read-only, so off the ADR-0046 recursion ladder.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from base_background_loop import BaseBackgroundLoop, LoopDeps
from events import EventType, HydraFlowEvent
from fitness_report import render_fitness_markdown, save_fitness_snapshots
from loop_fitness import (
    Confidence,
    FitnessContext,
    FitnessKind,
    IssueRecord,
    LoopFitness,
)

if TYPE_CHECKING:
    from config import HydraFlowConfig

_ARTIFACT_REL = Path("docs/arch/generated/loop-fitness.md")


class FitnessScorecardLoop(BaseBackgroundLoop):
    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        deps: LoopDeps,
        issue_fetcher: Callable[[], Awaitable[list[IssueRecord]]],
        repo_root: Path | None = None,
    ) -> None:
        super().__init__(worker_name="fitness_scorecard", config=config, deps=deps)
        self._issue_fetcher = issue_fetcher
        self._repo_root = repo_root or Path.cwd()
        self._loops: dict[str, BaseBackgroundLoop] = {}

    def set_loops(self, loops: dict[str, BaseBackgroundLoop]) -> None:
        self._loops = dict(loops)

    def _get_default_interval(self) -> int:
        return self._config.fitness_scorecard_interval

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        return LoopFitness(
            worker_name=self._worker_name,
            kind=FitnessKind.HOUSEKEEPING,
            confidence=Confidence.INSUFFICIENT_DATA,
            timestamp=ctx.window_end,
        )

    async def _do_work(self):
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        window_end = datetime.now(UTC)
        window_start = window_end - timedelta(days=self._config.fitness_window_days)

        events = await self._bus.load_events_since(window_start) or []
        status_by_worker: dict[str, list[dict]] = {}
        for event in events:
            if getattr(event, "type", None) != EventType.BACKGROUND_WORKER_STATUS:
                continue
            data = event.data if isinstance(event.data, dict) else {}
            worker = data.get("worker")
            if worker:
                status_by_worker.setdefault(worker, []).append(data)

        issues = await self._issue_fetcher()

        results: list[LoopFitness] = []
        for name, loop in self._loops.items():
            ctx = FitnessContext(
                window_start=window_start,
                window_end=window_end,
                worker_status=status_by_worker.get(name, []),
                issues=issues,
            )
            results.append(loop.loop_fitness(ctx))

        save_fitness_snapshots(self._config, results)

        artifact = self._repo_root / _ARTIFACT_REL
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(render_fitness_markdown(results))

        scored = sum(1 for r in results if r.kind == FitnessKind.SCORED)
        payload = {
            "generated_at": window_end.isoformat(),
            "window_days": self._config.fitness_window_days,
            "loop_count": len(results),
            "scored_count": scored,
        }
        await self._bus.publish(
            HydraFlowEvent(type=EventType.LOOP_FITNESS_UPDATE, data=payload)
        )
        return payload
