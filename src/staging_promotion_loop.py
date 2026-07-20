"""Promotion loop — cuts rc/* snapshots from staging and promotes them to main.

Runs on a tight poll interval (``staging_promotion_interval``, default 300s)
but actually cuts a new RC branch only every ``rc_cadence_hours`` (default 4h).
Between cuts it monitors the existing promotion PR: on green it merges with a
merge commit (ADR-0042 forbids squash here), on red it files a ``hydraflow-find``
issue and closes the PR so the next cadence tick can try again.

Gated by ``staging_enabled``; no-op when false.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import ci_sentinels
import evidence_pack
import subprocess_util
from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from events import EventType, HydraFlowEvent
from exception_classify import exc_detail, reraise_on_credit_or_bug
from merge_policy import (
    ROLE_ORCHESTRATOR_REVIEWER,
    MergeApproval,
    PolicyVerdict,
    enforce_merge_policy,
)
from models import SystemAlertPayload
from repro_manifest import append_manifest
from rollup_issue_manager import RollupIssueManager

if TYPE_CHECKING:
    from ports import PRPort
    from state import StateTracker

logger = logging.getLogger("hydraflow.staging_promotion_loop")

# gh timeout tier (see docs/wiki: subprocess timeout tiers — gh=30s).
_GH_TIMEOUT_SECONDS = 30.0

# How many recently merged main-base PRs one CH-4 reconcile sweep scans.
# Bounds the backlog the sweep can self-heal after downtime — RCs that
# merged before the newest N main-base merges are out of adoption scope and
# are not backfilled (the same adoption-baseline principle as CH-2's
# ``_MERGED_PR_SCAN_LIMIT`` in approval_records.py).
_MERGED_RC_SCAN_LIMIT = 20

# #10009: multiplier on rc_cadence_hours for the boot-time "missed cadence by
# a wide margin" warning. The ordinary cadence gate (_cadence_elapsed) already
# cuts immediately once >= rc_cadence_hours has passed — that's normal
# steady-state behaviour, not evidence of downtime. Crossing 1.5x is wide
# enough to signal the factory PROCESS itself was likely down (crash, host
# reboot, deploy gap) rather than just landing on a routine tick late.
_MISSED_CADENCE_ALERT_MULTIPLIER = 1.5


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
        # CH-4 (#9732): one SYSTEM_ALERT per RC whose evidence pack failed to
        # compile — re-fires for the next RC, never per retry of the same one.
        self._evidence_alert_dedup = DedupStore(
            "evidence_pack_alerts",
            config.data_root / "dedup" / "evidence_pack_alerts.json",
        )
        # CH-3 (#9731): one "Blocked by merge policy" comment + SYSTEM_ALERT
        # per (PR, deny reason-class) — a standing deny (e.g. corrupt
        # policy.yaml, the designed fail-closed state) must not re-spam every
        # promotion tick. A later allow verdict for the same PR re-arms.
        self._policy_deny_dedup = DedupStore(
            "policy_deny_alerts",
            config.data_root / "dedup" / "policy_deny_alerts.json",
        )
        # #10009: fires the missed-cadence boot check at most once per loop
        # lifetime — the loop's own catch-up cycle already runs _do_work
        # immediately after downtime (BaseBackgroundLoop._should_run_catchup),
        # so subsequent steady-state ticks must not re-log the boot warning.
        self._boot_cadence_checked = False

    def _get_default_interval(self) -> int:
        return self._config.staging_promotion_interval

    def _rollups(self, labels: list[str] | None = None) -> RollupIssueManager | None:
        """One rolling issue per subject under the ``staging_promotion``
        namespace — ``rc_ci`` ("promotion CI is failing", #9359) and
        ``rc_promotion_stuck`` (the streak escalation, #10015) — auto-closed
        on a green promotion. Replaces the per-PR ``RC promotion #N failed
        CI`` pile-up (#9219..#9342). ``None`` when state is absent (unit
        tests fall back to create_issue's stable-title dedup). *labels*
        overrides the default find-label set at create time; ``resolve`` is
        label-independent, so any instance can close any tracked subject."""
        if self._state is None:
            return None
        return RollupIssueManager(
            pr=self._prs,
            state=self._state,
            namespace="staging_promotion",
            labels=(
                labels
                if labels is not None
                else list(self._config.find_label or ["hydraflow-find"])
            ),
        )

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._boot_cadence_checked:
            self._check_missed_cadence_at_boot()

        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        if not self._config.staging_enabled:
            return {"status": "staging_disabled"}

        swept = await self._sweep_if_due()

        existing = await self._prs.find_open_promotion_pr()
        if existing is not None:
            result = await self._handle_open_promotion(existing.number, existing.branch)
        elif not self._cadence_elapsed():
            result = {"status": "cadence_not_elapsed"}
        else:
            result = await self._cut_new_rc()

        # CH-4 hardening: catch RCs merged outside this loop's own merge call
        # (operator force-merge, Monitor-driven merge, a merge that landed
        # after our call reported failure). Runs AFTER the promotion work and
        # never affects it — fail-open inside.
        reconciled = await self._reconcile_missing_packs()

        if swept:
            result = {**result, "swept": swept}
        if reconciled:
            result = {**result, "packs_reconciled": reconciled}
        return result

    async def _handle_open_promotion(
        self, pr_number: int, rc_branch: str
    ) -> dict[str, Any]:
        passed, summary = await self._prs.wait_for_ci(
            pr_number,
            timeout=60,
            poll_interval=15,
            stop_event=self._stop_event,
        )
        if passed:
            # CH-3 (#9731): consult the factory-autonomy policy before the
            # autonomous promotion merge. This lane's standing evidence is
            # the ADR-0042 two-tier grant: main only advances via CI-green
            # rc/* PRs whose commits each cleared the policy-gated
            # staging-side merges. A deny leaves the RC PR open for the
            # operator (approve, override, or fix the policy).
            policy_verdict = await enforce_merge_policy(
                config=self._config,
                prs=self._prs,
                pr_number=pr_number,
                actor="hydraflow:staging_promotion_loop",
                approvals=[
                    MergeApproval(
                        actor="staging_promotion_loop",
                        role=ROLE_ORCHESTRATOR_REVIEWER,
                        source="adr0042_rc_promotion_ci_green",
                    )
                ],
                lane="staging_promotion_loop",
            )
            if not policy_verdict.allowed:
                logger.warning(
                    "RC promotion PR #%d blocked by merge policy: %s",
                    pr_number,
                    policy_verdict.reason,
                )
                # LOUD by design (review finding): promotion runs on a
                # cadence, so a silent deny is an invisible outage of the
                # staging->main lane until someone reads PR comments.
                # Deduped per (PR, deny reason-class) — a standing deny (e.g.
                # corrupt policy.yaml, the designed fail-closed state) must
                # not bury the one actionable comment/alert under a per-tick
                # duplicate pile; a later allow verdict re-arms.
                deny_key = self._policy_deny_key(pr_number, policy_verdict)
                if deny_key in self._policy_deny_dedup.get():
                    return {"status": "policy_denied", "pr": pr_number}
                self._policy_deny_dedup.add(deny_key)
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.SYSTEM_ALERT,
                        data=SystemAlertPayload(
                            message=(
                                f"Merge policy denied RC promotion PR "
                                f"#{pr_number}: {policy_verdict.reason} — "
                                "staging->main promotion is blocked until "
                                "approved, overridden, or the policy is fixed."
                            ),
                            source="merge_policy",
                        ),
                    )
                )
                await self._prs.post_comment(
                    pr_number,
                    f"Blocked by merge policy: {policy_verdict.reason}\n\n"
                    "Approve the PR (or add a `policy-override:<reason-slug>` "
                    "label for an audited break-glass merge). "
                    "See docs/standards/factory_autonomy/policy.yaml.",
                )
                return {"status": "policy_denied", "pr": pr_number}
            # An allow verdict for this PR ends the deny event: re-arm so a
            # NEW distinct deny (same PR, later tick) alerts again.
            self._clear_policy_deny_dedup(pr_number)
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
                        # #10015: the streak escalation gets the same green-path
                        # resolve as rc_ci — before this it was a dead letter
                        # (a green promotion only reset the counter; #9867
                        # closed only via an unrelated PR body). Idempotent
                        # no-op when no escalation is tracked.
                        await rollups.resolve(
                            "rc_promotion_stuck",
                            comment=(
                                f"RC promotion to {self._config.main_branch} "
                                "succeeded — the consecutive-failure streak is "
                                "broken; auto-closing this escalation."
                            ),
                        )
                # CH-4 (#9732): the promotion succeeded — compile its release
                # evidence pack. LAST, after all promotion bookkeeping: the
                # pack is report-only and must never affect the result.
                await self._compile_evidence_pack(pr_number, rc_branch)
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

    async def _compile_evidence_pack(self, pr_number: int, rc_branch: str) -> None:
        """CH-4 (#9732): compile the release evidence pack for a promoted RC.

        Compile-only, report-only, fail-open: the promotion already happened,
        so a compiler failure logs a warning and publishes ONE SYSTEM_ALERT
        per RC (DedupStore'd on the rc branch) — it never affects the
        promotion result, and pack completeness never gates anything (gaps
        are named in the pack itself; tightening is a later decision).
        """
        if not self._config.evidence_pack_enabled or self._config.dry_run:
            return
        try:
            disabled = (
                self._state.get_disabled_workers() if self._state is not None else None
            )
            await evidence_pack.compile_evidence_pack(
                self._config, rc_branch, pr_number, disabled_workers=disabled
            )
        except Exception as exc:
            # Credit-exhaustion / likely-bug signals must propagate, not be
            # swallowed by the fail-open guard (dark-factory §2.2).
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "Evidence-pack compilation failed for promoted RC PR #%d (%s): %s",
                pr_number,
                rc_branch,
                exc_detail(exc),
                exc_info=True,
            )
            dedup_key = f"evidence_pack_failed:{rc_branch}"
            if dedup_key in self._evidence_alert_dedup.get():
                return
            self._evidence_alert_dedup.add(dedup_key)
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.SYSTEM_ALERT,
                    data=SystemAlertPayload(
                        message=(
                            f"Evidence-pack compilation failed for promoted RC "
                            f"PR #{pr_number} ({rc_branch}): {exc_detail(exc)} — "
                            "the promotion itself succeeded, but this RC has no "
                            "release evidence binder."
                        ),
                        source="evidence_pack",
                    ),
                )
            )

    @staticmethod
    def _policy_deny_key(pr_number: int, verdict: PolicyVerdict) -> str:
        """Dedup key for one deny event: ``<pr>:<reason-class>``.

        The reason-class is the policy entry that denied (stable across
        ticks) or ``policy_unloadable`` for the fail-closed no-decision
        shape — never the raw reason string, whose exception detail varies.
        """
        reason_class = (
            verdict.decision.entry_id
            if verdict.decision is not None
            else "policy_unloadable"
        )
        return f"{pr_number}:{reason_class}"

    def _clear_policy_deny_dedup(self, pr_number: int) -> None:
        """Drop every deny-dedup entry for *pr_number* (verdict now allows)."""
        current = self._policy_deny_dedup.get()
        kept = {k for k in current if not k.startswith(f"{pr_number}:")}
        if kept != current:
            self._policy_deny_dedup.set_all(kept)

    async def _reconcile_missing_packs(self) -> int | None:
        """CH-4 hardening: compile packs for merged RCs this loop didn't see.

        The promoted-path trigger fires only when THIS loop's own
        ``merge_promotion_pr`` call returns True. An RC merged by any other
        actor — an operator force-merge (exactly the case CH-2 records as
        role "operator"), a Monitor-driven merge, or a merge that landed
        after our call reported failure — would otherwise get no pack, no
        chained record, and no alert: a silent missing binder. Each tick
        this sweep diffs gh's recently merged promotion PRs against the
        ``evidence_packs`` stream and compiles whatever is missing, through
        the same kill-switch/dry-run/fail-open/alert machinery as the
        promoted-path trigger. Backlog is bounded by
        :data:`_MERGED_RC_SCAN_LIMIT`. Fail-open: a sweep error never
        affects the tick's promotion work.
        """
        if not self._config.evidence_pack_enabled or self._config.dry_run:
            return None
        try:
            merged = await self._list_merged_promotion_prs()
            if not merged:
                return 0
            packed = self._packed_pr_numbers()
            count = 0
            for pr_number, rc_branch in merged:
                if pr_number in packed:
                    continue
                logger.info(
                    "Evidence-pack reconcile: merged RC PR #%d (%s) has no "
                    "pack on the evidence_packs stream; compiling",
                    pr_number,
                    rc_branch,
                )
                await self._compile_evidence_pack(pr_number, rc_branch)
                count += 1
            return count
        except Exception as exc:
            # Credit-exhaustion / likely-bug signals must propagate, not be
            # swallowed by the fail-open guard (dark-factory §2.2).
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "Evidence-pack reconcile sweep failed: %s",
                exc_detail(exc),
                exc_info=True,
            )
            return None

    async def _list_merged_promotion_prs(self) -> list[tuple[int, str]]:
        """Recently merged RC promotion PRs as ``(pr_number, rc_branch)``.

        Raw ``gh`` at the 30s tier (approval_records.py precedent): no
        PRPort method lists merged PRs with head-branch info, and the atomic
        Protocol+fake+cassette triplet is not warranted for one read shape.
        Scans main-base merges and keeps heads matching
        ``rc_branch_prefix``.
        """
        raw = await subprocess_util.run_subprocess(
            "gh",
            "pr",
            "list",
            "--repo",
            self._config.repo,
            "--state",
            "merged",
            "--base",
            self._config.main_branch,
            "--limit",
            str(_MERGED_RC_SCAN_LIMIT),
            "--json",
            "number,headRefName",
            timeout=_GH_TIMEOUT_SECONDS,
        )
        data = json.loads(raw or "[]")
        if not isinstance(data, list):
            raise ValueError(f"gh pr list returned non-list payload: {data!r}")
        merged: list[tuple[int, str]] = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            number = entry.get("number")
            head = entry.get("headRefName")
            if (
                isinstance(number, int)
                and isinstance(head, str)
                and head.startswith(self._config.rc_branch_prefix)
            ):
                merged.append((number, head))
        return merged

    def _packed_pr_numbers(self) -> set[int]:
        """RC PR numbers already recorded on the ``evidence_packs`` stream.

        Read-back dedup (approval_records.py precedent): the chained stream
        is the single source of truth — no side store to drift.
        """
        path = self._config.evidence_packs_path
        if not path.exists():
            return set()
        numbers: set[int] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError:
                # A corrupt line is a chain break — RunsGCLoop alerts on it;
                # dedup keeps working from the parseable records.
                continue
            if not isinstance(record, dict):
                continue
            record_type = record.get(
                "record_type", evidence_pack.RECORD_TYPE_EVIDENCE_PACK
            )
            if record_type != evidence_pack.RECORD_TYPE_EVIDENCE_PACK:
                continue
            if isinstance(record.get("pr_number"), int):
                numbers.add(record["pr_number"])
        return numbers

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

        #10015: tracked as the ``rc_promotion_stuck`` rollup subject so the
        next green promotion auto-closes it (mirrors ``rc_ci``). The title is
        STABLE per the rollup contract — the streak size and latest PR number
        live in the body.
        """
        labels = list(self._config.hitl_escalation_label or ["hitl-escalation"])
        for lbl in self._config.rc_promotion_stuck_label:
            if lbl not in labels:
                labels.append(lbl)
        title = (
            f"staging→{self._config.main_branch} promotion stuck: "
            "repeated consecutive RC failures"
        )
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
            "clears the counter and auto-closes this escalation (#10015)."
        )
        rollups = self._rollups(labels=labels)
        if rollups is not None:
            return await rollups.ensure("rc_promotion_stuck", title=title, body=body)
        # State-less fallback (unit tests): create_issue's exact-title dedup on
        # the now-stable title still prevents per-streak pile-up.
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
        # CH-7 (#9735): the RC PR body is the exact document CH-4's
        # evidence-pack compiler reads the reproducibility manifest back from
        # (``_rc_repro_manifest``) — attach it here like pr_manager.create_pr
        # does. Fail-open inside append_manifest: a manifest error must never
        # block the RC cut.
        body = append_manifest(body, config=self._config)
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

    def _check_missed_cadence_at_boot(self) -> None:
        """Log loudly if the last RC cut is more than
        :data:`_MISSED_CADENCE_ALERT_MULTIPLIER` x ``rc_cadence_hours`` behind
        (#10009). Runs once per loop lifetime (guarded by
        ``self._boot_cadence_checked`` in ``_do_work``) — this is a
        diagnostic signal for "the factory process itself was down", not a
        behaviour change: :meth:`_cadence_elapsed` already cuts a new RC
        immediately once the plain cadence has elapsed, on this same first
        tick.
        """
        self._boot_cadence_checked = True
        path = self._cadence_path()
        if not path.exists():
            return  # no prior marker (first-ever run) — nothing was "missed"
        try:
            last = datetime.fromisoformat(path.read_text().strip())
        except ValueError:
            return
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        elapsed_hours = (datetime.now(UTC) - last).total_seconds() / 3600
        threshold_hours = (
            self._config.rc_cadence_hours * _MISSED_CADENCE_ALERT_MULTIPLIER
        )
        if elapsed_hours > threshold_hours:
            logger.warning(
                "StagingPromotionLoop missed its RC cadence by a wide "
                "margin: last RC cut %.1fh ago (cadence=%dh, alert "
                "threshold=%.1fh) — the factory process was likely down; "
                "cutting an RC immediately instead of waiting for the next "
                "cadence tick.",
                elapsed_hours,
                self._config.rc_cadence_hours,
                threshold_hours,
            )

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
