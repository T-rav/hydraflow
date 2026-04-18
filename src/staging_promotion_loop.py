"""Promotion loop — cuts rc/* snapshots from staging and promotes them to main.

Runs on a tight poll interval (``staging_promotion_interval``, default 300s)
but actually cuts a new RC branch only every ``rc_cadence_hours`` (default 4h).
Between cuts it monitors the existing promotion PR: on green it merges with a
merge commit (ADR-0042 forbids squash here), on red it files a ``hydraflow-find``
issue and closes the PR so the next cadence tick can try again.

Gated by ``staging_enabled``; no-op when false.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig

if TYPE_CHECKING:
    from ports import PRPort

logger = logging.getLogger("hydraflow.staging_promotion_loop")


class StagingPromotionLoop(BaseBackgroundLoop):
    """Periodic staging→main release-candidate promoter. See ADR-0042."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        prs: PRPort,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="staging_promotion", config=config, deps=deps)
        self._prs = prs

    def _get_default_interval(self) -> int:
        return self._config.staging_promotion_interval

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._config.staging_enabled:
            return {"status": "staging_disabled"}

        existing = await self._prs.find_open_promotion_pr()
        if existing is not None:
            return await self._handle_open_promotion(existing.number)

        if not self._cadence_elapsed():
            return {"status": "cadence_not_elapsed"}

        return await self._cut_new_rc()

    async def _handle_open_promotion(self, pr_number: int) -> dict[str, Any]:
        passed, summary = await self._prs.wait_for_ci(
            pr_number,
            timeout=60,
            poll_interval=15,
            stop_event=self._stop_event,
        )
        if passed:
            merged = await self._prs.merge_promotion_pr(pr_number)
            if merged:
                logger.info("Promoted RC PR #%d to main", pr_number)
                return {"status": "promoted", "pr": pr_number}
            logger.warning("Promotion merge failed for PR #%d", pr_number)
            return {"status": "merge_failed", "pr": pr_number}

        if "timed out" in summary.lower():
            return {"status": "ci_pending", "pr": pr_number}

        await self._prs.post_comment(
            pr_number,
            f"Promotion CI failed — closing, next cadence cycle will retry.\n\n{summary}",
        )
        await self._prs.close_issue(pr_number)
        logger.warning("Promotion PR #%d closed after CI failure", pr_number)
        return {"status": "ci_failed", "pr": pr_number}

    async def _cut_new_rc(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        rc_branch = f"{self._config.rc_branch_prefix}{now.strftime('%Y-%m-%d-%H%M')}"
        try:
            await self._prs.create_rc_branch(rc_branch)
        except RuntimeError:
            logger.exception("Failed to create RC branch %s", rc_branch)
            return {"status": "rc_branch_failed"}

        title = f"Promote {rc_branch} → {self._config.main_branch}"
        body = (
            f"Automated release-candidate promotion PR.\n\n"
            f"Source: `{rc_branch}` (snapshot of `{self._config.staging_branch}` "
            f"cut at {now.isoformat(timespec='seconds')}).\n\n"
            "See ADR-0042 for context."
        )
        try:
            pr_number = await self._prs.create_promotion_pr(
                rc_branch=rc_branch,
                title=title,
                body=body,
            )
        except RuntimeError:
            logger.exception("Failed to open promotion PR for %s", rc_branch)
            return {"status": "promotion_pr_failed", "rc_branch": rc_branch}

        self._record_last_rc(now)
        logger.info("Opened promotion PR #%d for %s", pr_number, rc_branch)
        return {"status": "opened", "pr": pr_number, "rc_branch": rc_branch}

    def _cadence_path(self) -> Path:
        return self._config.data_root / "memory" / ".staging_promotion_last_rc"

    def _cadence_elapsed(self) -> bool:
        path = self._cadence_path()
        if not path.exists():
            return True
        try:
            last = datetime.fromisoformat(path.read_text().strip())
        except ValueError:
            return True
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        elapsed_hours = (datetime.now(UTC) - last).total_seconds() / 3600
        return elapsed_hours >= self._config.rc_cadence_hours

    def _record_last_rc(self, when: datetime) -> None:
        path = self._cadence_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(when.isoformat())
