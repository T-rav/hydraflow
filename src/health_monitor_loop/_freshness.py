"""Content and deploy freshness checks of ``HealthMonitorLoop``.

Extracted VERBATIM from ``src/health_monitor_loop.py`` (god-class
decomposition, Refs #11547) as a mixin.

One concern: artefacts that go stale while everything still ticks — an
unrefreshed repo wiki and a factory running code behind its own remote — plus
the shared recovery close used by every detector in the package.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from config import Credentials, HydraFlowConfig
from dedup_store import DedupStore
from events import EventType, HydraFlowEvent
from git_revision import get_commits_behind
from subprocess_util import run_subprocess

from ._common import (
    _STALE_CODE_FETCH_TIMEOUT_SECS,
)

if TYPE_CHECKING:
    from events import EventBus
    from ports import PRPort


logger = logging.getLogger("hydraflow.health_monitor_loop")


class HealthMonitorFreshnessMixin:
    """Content and deploy freshness checks of ``HealthMonitorLoop``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``HealthMonitorLoop.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _bus: EventBus
    _config: HydraFlowConfig
    _credentials: Credentials
    _prs: PRPort | None
    _stale_code_dedup: DedupStore
    _wiki_stall_dedup: DedupStore

    async def _check_wiki_freshness(self) -> None:
        """Dead-man-switch for `RepoWikiLoop` via `docs/wiki/log.jsonl` mtime.

        The wiki loop appends to `log.jsonl` on every ingest, compile, and
        active_lint operation. When the file's mtime hasn't moved in
        `wiki_freshness_stale_days`, file one `wiki-stale` issue per stall
        event. Clears dedup on recovery (file moves again).

        Quietly no-ops when the wiki directory or log file does not exist —
        new repos won't have one yet, and that is not a stall.
        """
        prs = self._prs
        if prs is None:
            return

        log_path = self._config.repo_root / "docs" / "wiki" / "log.jsonl"
        if not log_path.exists():
            return

        try:
            mtime = datetime.fromtimestamp(log_path.stat().st_mtime, tz=UTC)
        except OSError:
            return

        elapsed_s = (datetime.now(UTC) - mtime).total_seconds()
        threshold_s = self._config.wiki_freshness_stale_days * 86400

        dedup_key = "health_monitor:repo_wiki:stalled"
        filed_keys = self._wiki_stall_dedup.get()

        if elapsed_s < threshold_s:
            # Recovered — close the open wiki-stale issue and clear dedup so a
            # future stall files a fresh issue (#9359 issue-hygiene).
            if dedup_key in filed_keys:
                await self._close_issues_by_label(
                    prs,
                    "wiki-stale",
                    "docs/wiki/log.jsonl is moving again — auto-closing.",
                )
                self._wiki_stall_dedup.set_all(filed_keys - {dedup_key})
            return

        if dedup_key in filed_keys:
            # Already filed for the current stall; wait for recovery.
            return

        elapsed_days = int(elapsed_s // 86400)
        title = (
            f"wiki-stale: docs/wiki/log.jsonl has not moved in "
            f"{elapsed_days}d (threshold {self._config.wiki_freshness_stale_days}d)"
        )
        body = (
            f"## RepoWikiLoop dead-man-switch tripped\n\n"
            f"`docs/wiki/log.jsonl` is the append-only operation log for the "
            f"repo wiki. It moves on every ingest, compile, and active_lint "
            f"tick; an unmoved log indicates the wiki loop has not run "
            f"successfully in `{elapsed_days}` days.\n\n"
            f"- Last log entry: `{mtime.isoformat()}`\n"
            f"- Threshold: `{self._config.wiki_freshness_stale_days}` days "
            f"(`wiki_freshness_stale_days`)\n"
            f"- Loop interval: `{self._config.repo_wiki_interval}s`\n\n"
            f"### Operator playbook\n"
            f"1. Check the System tab — is `repo_wiki` enabled? If not, "
            f"flip the kill-switch back on.\n"
            f"2. Check orchestrator logs for the `repo_wiki` task "
            f"(uncaught exceptions, credit/auth failures).\n"
            f"3. Confirm HydraFlow is actually running on this repo "
            f"(the loop only ticks while the harness is up).\n\n"
            f"_Auto-filed by HydraFlow `health_monitor` "
            f"(wiki-freshness dead-man-switch)._"
        )
        await prs.create_issue(
            title,
            body,
            ["hydraflow-find", "wiki-stale"],
        )
        filed_keys = self._wiki_stall_dedup.get()
        self._wiki_stall_dedup.set_all(filed_keys | {dedup_key})

    async def _check_stale_code(self) -> None:
        """Dead-man-switch: alert when this instance is running stale code.

        Consumes ``git_revision.get_commits_behind`` (#9663) for the
        commits-behind count against the in-memory boot SHA — this method
        does NOT recompute staleness itself. ``git_revision`` deliberately
        performs no network fetch (it only reads local tracking refs), so
        this loop owns a bounded, pre-read ``git fetch`` of
        ``origin/<base_branch>`` first; without it the local tracking ref
        can go stale indefinitely and the check would never trip.

        Files one ``factory-stale-code`` issue (deduped) plus one
        ``SYSTEM_ALERT`` dashboard event per stall event when
        ``commits_behind >= stale_code_alert_threshold``. Recovery (a
        fresh process boots onto current code, or origin catches up)
        closes the open issue and clears dedup so a future stall re-files.

        Fails safe: an unreachable remote (fetch failure) or an
        unavailable boot SHA / commit count (``get_commits_behind``
        returns ``None``) degrades this tick to a silent no-op — neither
        files nor clears an alert, since neither the stale nor the
        recovered state was actually confirmed.
        """
        prs = self._prs
        if prs is None:
            return

        base_branch = self._config.base_branch()
        try:
            await run_subprocess(
                "git",
                "fetch",
                "origin",
                base_branch,
                cwd=self._config.repo_root,
                gh_token=self._credentials.gh_token,
                timeout=_STALE_CODE_FETCH_TIMEOUT_SECS,
            )
        except RuntimeError:
            # Includes SubprocessTimeoutError (RuntimeError subclass).
            # Degrade — do not compute or alert against a possibly-stale
            # local tracking ref.
            logger.warning(
                "stale-code check: git fetch origin %s failed; skipping this cycle",
                base_branch,
                exc_info=True,
            )
            return

        commits_behind = get_commits_behind(base_ref=f"origin/{base_branch}")
        if commits_behind is None:
            # Boot SHA or commit count unavailable (e.g. not a git checkout)
            # — fail-safe no-op, per git_revision's own contract.
            return

        threshold = self._config.stale_code_alert_threshold
        dedup_key = "health_monitor:stale_code:stale"
        filed_keys = self._stale_code_dedup.get()

        if commits_behind < threshold:
            # Recovered (or never stale) — close any open alert and clear
            # dedup so a future stall re-files (#9359 issue-hygiene).
            if dedup_key in filed_keys:
                await self._close_issues_by_label(
                    prs,
                    "factory-stale-code",
                    f"This instance is back within {threshold} commits of "
                    f"origin/{base_branch} — auto-closing.",
                )
                self._stale_code_dedup.set_all(filed_keys - {dedup_key})
            return

        if dedup_key in filed_keys:
            # Already filed for the current stall; wait for recovery.
            return

        title = (
            f"factory-stale-code: running instance is {commits_behind} "
            f"commits behind origin/{base_branch} (threshold {threshold})"
        )
        body = (
            f"## Stale-code dead-man-switch tripped\n\n"
            f"This HydraFlow instance's boot commit is `{commits_behind}` "
            f"commits behind `origin/{base_branch}`, at or past the "
            f"configured threshold of `{threshold}` "
            f"(`stale_code_alert_threshold`).\n\n"
            f"The boot SHA is captured once, in-memory, at process start "
            f"and never re-read — a `git pull` without a process restart "
            f"advances the working-tree HEAD while the process keeps "
            f"running the stale bytecode, so this check does not "
            f"self-clear until the process actually restarts onto fresh "
            f"code.\n\n"
            f"### Operator playbook\n"
            f"1. Check `GET /api/control/status` for `boot_sha` / "
            f"`commits_behind`.\n"
            f"2. Restart the orchestrator (`systemctl restart hydraflow` "
            f"or equivalent) to boot onto current `origin/{base_branch}`.\n"
            f"3. If this keeps tripping right after a restart, check "
            f"whether the deploy pulls before restarting.\n\n"
            f"_Auto-filed by HydraFlow `health_monitor` "
            f"(stale-code dead-man-switch, #9596)._"
        )
        await prs.create_issue(
            title,
            body,
            ["hydraflow-find", "factory-stale-code"],
        )
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.SYSTEM_ALERT,
                data={
                    "kind": "factory_stale_code",
                    "commits_behind": commits_behind,
                    "threshold": threshold,
                    "base_branch": base_branch,
                },
            )
        )
        filed_keys = self._stale_code_dedup.get()
        self._stale_code_dedup.set_all(filed_keys | {dedup_key})

    async def _close_issues_by_label(
        self,
        prs: PRPort,
        label: str,
        comment: str,
        *,
        title_contains: str | None = None,
    ) -> None:
        """Close every open issue carrying *label* when a dead-man-switch
        recovers (#9359). Titles embed elapsed-time so they can't be found by
        title; the label is the stable handle. ``title_contains`` narrows to
        one worker's issues when the label is shared (generic stall sweep)."""
        try:
            issues = await prs.list_issues_by_label(label)
        except Exception:  # noqa: BLE001
            logger.warning(
                "health_monitor: could not list %s issues to close",
                label,
                exc_info=True,
            )
            return
        for issue in issues:
            number = issue.get("number")
            if not number:
                continue
            if title_contains is not None and title_contains not in str(
                issue.get("title", "")
            ):
                continue
            await prs.post_comment(number, comment)
            await prs.close_issue(number)
