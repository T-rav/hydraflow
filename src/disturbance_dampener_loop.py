"""Burn-down caretaker loop for the disturbance dampener (ADR-0095, Pattern A).

Each tick: select backlog units (per dimension+file, smallest-first, capped),
dispatch a coding agent to fix a file's violations + prune its baseline
signatures, and open one PR per file via generate_and_open_pr_async.
Mirrors SandboxFailureFixerLoop's runner/attempt-cap/kill-switch shape.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from auto_pr import generate_and_open_pr_async
from base_background_loop import BaseBackgroundLoop, LoopDeps
from disturbance.baseline import load_baseline
from disturbance.burndown import BurndownUnit, select_units
from disturbance.registry import DIMENSIONS
from exception_classify import reraise_on_credit_or_bug
from loop_fitness import FitnessContext, LoopFitness, proposal_acceptance_fitness

if TYPE_CHECKING:
    from disturbance.registry import DimensionSpec

logger = logging.getLogger("hydraflow.disturbance_dampener")

_DAMPENER_LABEL = "disturbance-dampener"


class DisturbanceDampenerLoop(BaseBackgroundLoop):
    # Longer watchdog: each unit dispatches an LLM agent.
    LONG_LLM_CYCLE = True

    def __init__(
        self,
        *,
        config: Any,
        state: Any,
        prs: Any,
        dedup: Any,
        deps: LoopDeps,
        runner: Any | None = None,
        dimensions: list[DimensionSpec] | None = None,
        baseline_loader: Callable[[Path], dict[str, int]] = load_baseline,
        pr_opener: Callable[..., Awaitable[Any]] | None = None,
    ) -> None:
        super().__init__(
            worker_name="disturbance_dampener",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._prs = prs
        self._dedup = dedup
        self._runner = runner
        self._dimensions = dimensions if dimensions is not None else DIMENSIONS
        self._load_baseline = baseline_loader
        self._pr_opener = pr_opener or generate_and_open_pr_async

    def _get_default_interval(self) -> int:
        return int(self._config.disturbance_dampener_interval_seconds)

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        # Burn-down effectiveness: merged fix-PRs / opened fix-PRs (label-scoped).
        return proposal_acceptance_fitness(
            ctx, worker_name=self._worker_name, label=_DAMPENER_LABEL
        )

    async def _do_work(self) -> dict[str, Any]:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.disturbance_dampener_enabled:
            return {"status": "config_disabled"}
        if self._runner is None or self._prs is None:
            return {"status": "ok", "opened": 0}

        repo_root = Path(self._config.repo_root)
        per_dim: list[tuple[str, str, list, dict[str, int]]] = []
        for spec in self._dimensions:
            findings = spec.detector.detect(repo_root)
            baseline_path = (
                spec.baseline_path
                if spec.baseline_path.is_absolute()
                else repo_root / spec.baseline_path
            )
            per_dim.append(
                (
                    spec.name,
                    spec.fix_prompt,
                    findings,
                    self._load_baseline(baseline_path),
                )
            )

        deduped = self._dedup.get()
        cap = int(self._config.disturbance_dampener_max_prs_per_tick)
        units = select_units(per_dim, deduped=deduped, cap=cap)

        opened = 0
        skipped = 0
        crashed = 0
        max_attempts = int(self._config.auto_agent_max_attempts)
        for unit in units:
            attempts = self._state.get_disturbance_dampener_attempts(unit.dedup_key)
            if attempts >= max_attempts:
                logger.warning(
                    "disturbance unit %s hit attempt cap (%d) — skipping",
                    unit.dedup_key,
                    attempts,
                )
                skipped += 1
                continue
            self._state.bump_disturbance_dampener_attempts(unit.dedup_key)
            try:
                result = await self._fix_unit(repo_root, unit)
            except Exception as exc:  # noqa: BLE001
                reraise_on_credit_or_bug(exc)
                logger.warning("disturbance fix failed for %s: %s", unit.dedup_key, exc)
                crashed += 1
                continue
            if getattr(result, "status", "") == "opened":
                opened += 1
                deduped.add(unit.dedup_key)
                self._dedup.set_all(deduped)
            else:
                skipped += 1
        return {
            "status": "ok",
            "candidates": len(units),
            "opened": opened,
            "skipped": skipped,
            "crashed": crashed,
        }

    async def _fix_unit(self, repo_root: Path, unit: BurndownUnit) -> Any:
        runner = self._runner
        assert runner is not None  # noqa: S101  # type narrow; guarded in _do_work
        dim = unit.dimension

        async def _generate(worktree: Path) -> None:
            outcome = await runner.run(
                prompt=self._build_prompt(unit),
                worktree_path=str(worktree),
                issue_number=0,
            )
            if getattr(outcome, "crashed", False):
                raise RuntimeError(f"agent crashed fixing {unit.dedup_key}")

        slug = unit.path.replace("/", "-").replace(".", "-")
        return await self._pr_opener(
            repo_root=repo_root,
            branch=f"agent/disturbance-{dim}-{slug}",
            generate=_generate,
            path_specs=[unit.path, f"disturbance/baselines/{dim}.yaml"],
            pr_title=f"chore(disturbance): burn down {dim} in {unit.path}",
            pr_body=self._build_prompt(unit),
            base=self._config.base_branch(),
            labels=[_DAMPENER_LABEL],
        )

    def _build_prompt(self, unit: BurndownUnit) -> str:
        sigs = "\n".join(f"  - {s}" for s in unit.signatures)
        return (
            f"Burn down `{unit.dimension}` violations in `{unit.path}`.\n\n"
            f"{unit.fix_prompt}\n\n"
            f"Signatures to eliminate (fix ALL of them in this file):\n{sigs}\n\n"
            f"After fixing, you MUST also prune the corresponding entries from "
            f"`disturbance/baselines/{unit.dimension}.yaml` (decrement or remove each "
            f"signature's count to match the new reality). The disturbance ratchet gate "
            f"in this PR verifies your work: if the code still has a violation the count "
            f"won't drop; if you prune the baseline without fixing the code the gate fails."
        )
