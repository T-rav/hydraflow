"""CharterLoopWorkerLoop — runs a repo's charter-declared loops on a tick.

#11861 shipped `CharterLoopRunner` as a dispatch component with no loop
registration. This is the driver that makes it a real loop in the factory:
ADR-0029 caretaker shape, kill switch per ADR-0049, dedup per the repo's
convention.

**What it owns and what it does not.** The runner decides which loops are due,
dispatches them inside their envelope, and receipts every decision. This loop
owns only the periodic *when*, the per-repo iteration, and the dedup that keeps
one scheduled window from firing twice — the caretaker half of the split
ADR-0143 Ruling 4 draws between deciding and acting.

**Dedup key is `repo:loop:window`, not `repo:loop`.** A loop that fires daily
must fire again tomorrow; keying on the loop alone would fire it once ever. The
window is the scheduled minute the runner resolved, so a second tick inside the
same window is suppressed while the next window is not — which is the same
catch-up policy the runner enforces, made durable across process restarts.

**A repo with no v2 charter is skipped, not failed.** Absent `loops:` means an
unmigrated repo (ADR-0145 guard 3), and every repo today is unmigrated. A
present-but-empty block is also skipped here for a different reason: it
declares that nothing runs, and there is nothing to dispatch.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from charter import load_charter
from charter_model import CharterError
from exception_classify import reraise_on_credit_or_bug
from loop_fitness import Confidence, FitnessContext, FitnessKind, LoopFitness

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from config import HydraFlowConfig
    from dedup_store import DedupStore

logger = logging.getLogger(__name__)


def dedup_key(repo: str, loop: str, window: str) -> str:
    """`repo:loop:window` — the scheduled window is part of the identity.

    Keying on `repo:loop` alone would fire a daily loop exactly once, ever.
    Keying on the window makes "already ran this window" durable across process
    restarts, which is what the runner's in-memory catch-up policy cannot be on
    its own.
    """
    return f"charter_loop:{repo}:{loop}:{window}"


class CharterLoopWorkerLoop(BaseBackgroundLoop):
    """Drives `CharterLoopRunner` across every managed repo with a v2 charter."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        dedup: DedupStore,
        deps: LoopDeps,
        runner_for: Any,
        repos: Any,
    ) -> None:
        super().__init__(worker_name="charter_loop_worker", config=config, deps=deps)
        self._dedup = dedup
        #: ``(repo_slug, repo_root) -> CharterLoopRunner``. Injected so this
        #: loop never constructs a runner — the runner needs a dispatch surface
        #: and a receipt writer, and wiring those here would put the factory's
        #: broker inside a caretaker.
        self._runner_for = runner_for
        #: ``() -> Sequence[tuple[str, Path]]`` of managed repos.
        self._repos = repos

    def _get_default_interval(self) -> int:
        return self._config.charter_loop_worker_interval

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        # DISPATCH, not housekeeping: this loop's output is other agents' work
        # reaching a PR, and its value is judged where that work is judged.
        # Counting its own ticks would report a healthy loop that dispatched
        # nothing.
        return LoopFitness(
            worker_name=self._worker_name,
            kind=FitnessKind.HOUSEKEEPING,
            confidence=Confidence.INSUFFICIENT_DATA,
            timestamp=ctx.window_end,
        )

    async def _do_work(self) -> dict[str, Any] | None:
        # ADR-0049: kill switch first, static config flag second.
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.charter_loop_worker_loop_enabled:
            return {"status": "config_disabled"}
        if self._config.dry_run:
            return None

        dedup = self._dedup.get()
        dispatched = 0
        skipped_unmigrated = 0
        deduped = 0

        for repo, repo_root in self._repos():
            try:
                charter = load_charter(repo_root)
            except CharterError:
                # Caught BEFORE the broad except on purpose. `CharterError`
                # subclasses ValueError, and `reraise_on_credit_or_bug`
                # classifies a ValueError as a likely bug and re-raises it —
                # correctly, for HydraFlow's own code. But a malformed charter
                # is the TARGET REPO's data, not a defect here: re-raising
                # would take the whole tick down over somebody else's typo, and
                # every other repo's loops with it.
                #
                # The drift caretaker reports it. This loop refuses to run
                # anything for that repo and moves on, never guessing at a
                # partial declaration.
                logger.warning(
                    "charter-loop: %s has an unreadable charter — running "
                    "nothing for it this tick",
                    repo,
                    exc_info=True,
                )
                continue
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "charter-loop: could not load %s's charter", repo, exc_info=True
                )
                continue

            if charter is None or not charter.loops.present:
                skipped_unmigrated += 1
                continue

            fired, suppressed = await self._run_repo(repo, repo_root, charter, dedup)
            dispatched += fired
            deduped += suppressed

        self._dedup.set_all(dedup)
        return {
            "status": "ran" if dispatched else "idle",
            "dispatched": dispatched,
            "deduped": deduped,
            "skipped_unmigrated": skipped_unmigrated,
        }

    async def _run_repo(
        self, repo: str, repo_root: Any, charter: Any, dedup: set[str]
    ) -> tuple[int, int]:
        """Run one repo's due loops. Returns ``(dispatched, deduped)``."""
        runner = self._runner_for(repo, repo_root)
        last_fired = _last_fired_from_dedup(charter, repo, dedup)

        try:
            receipts = await runner.tick(charter, last_fired=last_fired)
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("charter-loop: tick failed for %s", repo, exc_info=True)
            return 0, 0

        dispatched = 0
        deduped = 0
        for receipt in receipts:
            if not receipt.window:
                continue
            key = dedup_key(repo, receipt.loop, receipt.window)
            if key in dedup:
                deduped += 1
                continue
            dedup.add(key)
            dispatched += 1
        return dispatched, deduped


def _last_fired_from_dedup(
    charter: Any, repo: str, dedup: set[str]
) -> dict[str, datetime | None]:
    """Reconstruct each loop's last window from the dedup ledger.

    The dedup set IS the durable record of what has fired, so reading it back
    is what makes the catch-up policy survive a restart. A separate store would
    be a second place the same fact lives — and the two would drift the first
    time one of them was written and the other was not.
    """
    from datetime import datetime

    latest: dict[str, datetime | None] = {}
    prefix = f"charter_loop:{repo}:"
    for key in dedup:
        if not key.startswith(prefix):
            continue
        rest = key[len(prefix) :]
        loop, _, window = rest.partition(":")
        if not window:
            continue
        try:
            stamped = datetime.fromisoformat(window)
        except ValueError:
            continue
        known = latest.get(loop)
        if known is None or stamped > known:
            latest[loop] = stamped
    for loop in charter.loops.by_name():
        latest.setdefault(loop, None)
    return latest


def managed_repo_roots(config: HydraFlowConfig) -> Sequence[tuple[str, Any]]:
    """``(slug, root)`` for every repo this factory manages."""
    from pathlib import Path

    return [(config.repo, Path(config.repo_root))]
