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

import ci_sentinels
from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from rollup_issue_manager import RollupIssueManager

if TYPE_CHECKING:
    from ports import PRPort
    from state import StateTracker

logger = logging.getLogger("hydraflow.staging_promotion_loop")


class StagingPromotionLoop(BaseBackgroundLoop):
    """Periodic staging→main release-candidate promoter. See ADR-0042."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        prs: PRPort,
        deps: LoopDeps,
        state: StateTracker | None = None,
    ) -> None:
        super().__init__(worker_name="staging_promotion", config=config, deps=deps)
        self._prs = prs
        self._state = state

    def _get_default_interval(self) -> int:
        return self._config.staging_promotion_interval

    def _rollups(self) -> RollupIssueManager | None:
        """One rolling "promotion CI is failing" issue, auto-closed on a green
        promotion — replaces the per-PR ``RC promotion #N failed CI`` pile-up
        (#9219..#9342). ``None`` when state is absent (unit tests fall back to
        create_issue's stable-title dedup)."""
        if self._state is None:
            return None
        return RollupIssueManager(
            pr=self._prs,
            state=self._state,
            namespace="staging_promotion",
            labels=list(self._config.find_label or ["hydraflow-find"]),
        )

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        if not self._config.staging_enabled:
            return {"status": "staging_disabled"}

        swept = await self._sweep_if_due()

        existing = await self._prs.find_open_promotion_pr()
        if existing is not None:
            result = await self._handle_open_promotion(existing.number)
        elif not self._cadence_elapsed():
            result = {"status": "cadence_not_elapsed"}
        else:
            result = await self._cut_new_rc()

        if swept:
            result = {**result, "swept": swept}
        return result

    async def _handle_open_promotion(self, pr_number: int) -> dict[str, Any]:
        passed, summary = await self._prs.wait_for_ci(
            pr_number,
            timeout=60,
            poll_interval=15,
            stop_event=self._stop_event,
        )
        if passed:
            merged = await self._prs.merge_promotion_pr(pr_number, auto_rebase=True)
            if merged:
                logger.info("Promoted RC PR #%d to main", pr_number)
                if self._state is not None:
                    try:
                        head_sha = await self._prs.get_pr_head_sha(pr_number)
                    except Exception:  # noqa: BLE001
                        logger.debug(
                            "Could not read head SHA for promoted PR #%d",
                            pr_number,
                            exc_info=True,
                        )
                        head_sha = ""
                    if head_sha:
                        self._state.set_last_green_rc_sha(head_sha)
                        self._state.reset_auto_reverts_in_cycle()
                    # A green promotion clears the consecutive-failure streak so
                    # a future stall re-escalates from scratch (#9359 hardening).
                    self._state.reset_consecutive_rc_failures()
                    # CI is green again — close the single rolling "promotion CI
                    # failing" issue if one is open (#9359 issue-hygiene).
                    rollups = self._rollups()
                    if rollups is not None:
                        await rollups.resolve(
                            "rc_ci",
                            comment=(
                                f"RC promotion to {self._config.main_branch} "
                                "succeeded — auto-closing."
                            ),
                        )
                return {"status": "promoted", "pr": pr_number}
            logger.warning("Promotion merge failed for PR #%d", pr_number)
            return {"status": "merge_failed", "pr": pr_number}

        # wait_for_ci can return WITHOUT a CI verdict: a timeout (the poll window
        # elapsed while CI was still running) or "Stopped" (kill-switch fired
        # mid-poll). Neither is a CI failure — leave the PR open for the next
        # cadence tick rather than force-closing a still-green RC PR. The
        # sentinel + "incomplete" classification are single-sourced in
        # ci_sentinels so the producer (pr_manager) and this consumer can't drift
        # again — that drift stalled main promotion ~3 days (#9219..#9342, #9351).
        if ci_sentinels.is_ci_incomplete(summary):
            return {"status": "ci_pending", "pr": pr_number}

        issue_number = await self._file_failure_issue(pr_number, summary)
        await self._prs.post_comment(
            pr_number,
            f"Promotion CI failed — closing, next cadence cycle will retry.\n\n"
            f"Filed follow-up: #{issue_number}.\n\n{summary}",
        )
        await self._prs.close_issue(pr_number)
        logger.warning(
            "Promotion PR #%d closed after CI failure; filed #%d",
            pr_number,
            issue_number,
        )
        if self._state is not None:
            try:
                red_sha = await self._prs.get_pr_head_sha(pr_number)
            except Exception:  # noqa: BLE001
                logger.debug(
                    "Could not read head SHA for red PR #%d",
                    pr_number,
                    exc_info=True,
                )
                red_sha = ""
            if red_sha:
                self._state.set_last_rc_red_sha_and_bump_cycle(red_sha)
            # Repeated-failure escalation: one per-PR find-issue per failure
            # gives no signal that the WHOLE pipeline is stuck. After N
            # consecutive failures escalate ONCE to a human, so a multi-day stall
            # (like #9219..#9342, where main silently didn't advance for ~3 days)
            # can't pass unnoticed. Fires exactly once per streak (== threshold);
            # the next green promotion resets the counter. #9359 hardening.
            failures = self._state.increment_consecutive_rc_failures()
            if failures == self._config.rc_consecutive_failure_escalation_threshold:
                await self._file_repeated_failure_escalation(pr_number, failures)
        return {
            "status": "ci_failed",
            "pr": pr_number,
            "find_issue": issue_number,
        }

    async def _file_failure_issue(self, pr_number: int, summary: str) -> int:
        # STABLE title (no PR number) so a single rolling issue tracks "promotion
        # CI is currently failing", updated in place each cadence tick and closed
        # automatically on the next green promotion. The old per-PR title filed a
        # brand-new issue every tick (#9219..#9342). #9359 issue-hygiene.
        labels = list(self._config.find_label or ["hydraflow-find"])
        title = f"RC promotion to {self._config.main_branch} failing CI"
        body = (
            f"Automated promotion PR #{pr_number} failed CI and was closed.\n\n"
            f"The StagingPromotionLoop retries on each cadence tick; this issue "
            f"updates in place while staging→{self._config.main_branch} CI stays "
            f"red, and auto-closes on the next green promotion.\n\n"
            "Investigate whether the failure is:\n"
            "- a real regression → fix before the next cadence\n"
            "- a flake → re-open the PR or wait for the next cycle\n"
            "- an environmental issue → fix CI config\n\n"
            f"```\n{summary}\n```"
        )
        rollups = self._rollups()
        if rollups is not None:
            return await rollups.ensure("rc_ci", title=title, body=body)
        # State-less fallback (unit tests): create_issue's exact-title dedup on
        # the now-stable title still prevents per-tick pile-up.
        try:
            return await self._prs.create_issue(title, body, labels)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to file hydraflow-find issue for PR %d", pr_number)
            return 0

    async def _file_repeated_failure_escalation(
        self, pr_number: int, failures: int
    ) -> int:
        """Escalate to a human when promotions fail repeatedly.

        Per-PR ``RC promotion #N failed CI`` find-issues give no signal that the
        WHOLE staging→main pipeline is stuck — exactly how the #9351 timeout bug
        stalled ``main`` for ~3 days unnoticed. After
        ``rc_consecutive_failure_escalation_threshold`` consecutive failures we
        file ONE ``hitl-escalation`` issue so a human looks at the pipeline, not
        just the latest red PR.
        """
        labels = list(self._config.hitl_escalation_label or ["hitl-escalation"])
        for lbl in self._config.rc_promotion_stuck_label:
            if lbl not in labels:
                labels.append(lbl)
        title = f"staging→main promotion stuck: {failures} consecutive RC failures"
        body = (
            f"The StagingPromotionLoop has failed to promote `staging` → "
            f"`{self._config.main_branch}` **{failures} times in a row** "
            f"(latest: RC PR #{pr_number}). `main` is not advancing.\n\n"
            "A single rolling `RC promotion to main failing CI` issue tracks the "
            "red state, but this escalation means the pipeline needs a human:\n"
            "- a real regression on `staging` blocking every RC (run the failing "
            "gate locally to bisect), or\n"
            "- a systemic CI/promotion-loop defect (e.g. the #9351 timeout "
            "misclassification that silently force-closed green PRs).\n\n"
            "This fires once per failure streak; the next successful promotion "
            "clears the counter."
        )
        try:
            return await self._prs.create_issue(title, body, labels)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to file repeated-failure escalation (failures=%d)", failures
            )
            return 0

    async def _cut_new_rc(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        rc_branch = f"{self._config.rc_branch_prefix}{now.strftime('%Y-%m-%d-%H%M')}"
        try:
            await self._prs.create_rc_branch(rc_branch)
        except RuntimeError:
            logger.exception("Failed to create RC branch %s", rc_branch)
            return {"status": "rc_branch_failed"}

        # Pre-check: skip when staging is already identical to main. Opening a
        # promotion PR with zero commits ahead hard-fails on GitHub with
        # "GraphQL: No commits between main and <rc> (createPullRequest)" — a
        # recurring ERROR on every cadence tick during quiet periods. Treat the
        # empty-RC case as a clean no-op instead.
        if not await self._prs.branch_has_diff_from_main(rc_branch):
            self._record_last_rc(now)
            logger.info(
                "RC branch %s has no commits ahead of %s; skipping promotion PR",
                rc_branch,
                self._config.main_branch,
            )
            return {"status": "no_commits", "rc_branch": rc_branch}

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

        # Workaround for issue #8705: PRs whose head branch was created
        # via the git/refs API don't reliably fire pull_request:opened
        # workflows (CodeQL, Browser Scenarios, etc.). Push a synthetic
        # commit to fire pull_request:synchronize, which does trigger
        # workflows — required-status-checks then bind to the PR head SHA
        # and the auto-merge path can complete.
        try:
            await self._prs.push_synthetic_commit(
                rc_branch,
                f"chore(rc): trigger CI for {rc_branch} promotion PR (#{pr_number})",
            )
        except RuntimeError:
            logger.warning(
                "Failed to push synthetic CI-trigger commit on %s; "
                "workflows may not fire automatically — see issue #8705",
                rc_branch,
                exc_info=True,
            )

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

    def _sweep_path(self) -> Path:
        return self._config.data_root / "memory" / ".staging_promotion_last_sweep"

    def _sweep_due(self) -> bool:
        path = self._sweep_path()
        if not path.exists():
            return True
        try:
            last = datetime.fromisoformat(path.read_text().strip())
        except ValueError:
            return True
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return (datetime.now(UTC) - last).total_seconds() >= 86400

    async def _sweep_if_due(self) -> int | None:
        if not self._sweep_due():
            return None
        deleted = await self._sweep_stale_rc_branches()
        path = self._sweep_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(datetime.now(UTC).isoformat())
        return deleted

    async def _sweep_stale_rc_branches(self) -> int:
        branches = await self._prs.list_rc_branches()
        if not branches:
            return 0

        retention_seconds = self._config.staging_rc_retention_days * 86400
        now = datetime.now(UTC)

        dated: list[tuple[str, datetime]] = []
        for branch, iso in branches:
            try:
                when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            except ValueError:
                logger.debug("Un-parseable committer date %r on %s", iso, branch)
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            dated.append((branch, when))
        if not dated:
            return 0

        # Newest RC is always preserved even if older than the retention window,
        # so we never leave zero RC snapshots on the repo.
        dated.sort(key=lambda b: b[1], reverse=True)
        newest = dated[0][0]
        open_pr = await self._prs.find_open_promotion_pr()
        keep_branch = open_pr.branch if open_pr is not None else None

        deleted = 0
        for branch, when in dated[1:]:
            if branch == keep_branch:
                continue
            if (now - when).total_seconds() < retention_seconds:
                continue
            if await self._prs.delete_branch(branch):
                deleted += 1
                logger.info("Swept stale RC branch %s", branch)
        if deleted:
            logger.info(
                "Retention sweep: deleted %d rc/* branches (kept newest=%s)",
                deleted,
                newest,
            )
        return deleted
