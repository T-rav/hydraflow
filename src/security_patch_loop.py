"""Background worker loop — poll Dependabot alerts and file issues for fixable vulnerabilities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from rollup_issue_manager import RollupIssueManager

if TYPE_CHECKING:
    from ports import PRPort
    from state import StateTracker

logger = logging.getLogger("hydraflow.security_patch_loop")

# Severity levels ordered from most to least severe.
_SEVERITY_RANK: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}

# Dependabot alert states that mean "no longer an open vulnerability". Querying
# these explicitly (rather than closing "every tracked issue not in the open
# set") is what makes recovery safe: ``get_dependabot_alerts`` returns ``[]`` on
# a transient API error, so an open-set reconcile would mass-close every
# security issue. A resolved-state query that errors also returns ``[]`` — which
# closes nothing.
_RESOLVED_STATES: tuple[str, ...] = ("fixed", "dismissed", "auto_dismissed")


class SecurityPatchLoop(BaseBackgroundLoop):
    """Periodically polls Dependabot alerts and files issues for fixable vulnerabilities.

    Only processes alerts at or above the configured severity threshold and
    that have a ``first_patched_version`` available.  One open issue is kept per
    alert via :class:`RollupIssueManager` (namespace ``security_patch``); when
    GitHub reports the alert ``fixed``/``dismissed`` the issue is auto-closed
    (#9359).
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        pr_manager: PRPort,
        state: StateTracker,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="security_patch", config=config, deps=deps)
        self._pr_manager = pr_manager
        self._state = state

    def _get_default_interval(self) -> int:
        return self._config.security_patch_interval

    def _rollups(self) -> RollupIssueManager:
        """One open ``security`` issue per Dependabot alert number.

        ``RollupIssueManager`` subsumes the old local ``DedupStore`` *and* the
        GitHub-side dedup backstop: ``ensure`` tracks the issue number in
        ``state.rollup_issues`` and, if that state is lost, ``create_issue``'s
        exact-title dedup returns the existing number so the issue is re-adopted
        rather than duplicated.
        """
        return RollupIssueManager(
            pr=self._pr_manager,
            state=self._state,
            namespace="security_patch",
            labels=["security"],
        )

    def _meets_severity(self, severity: str) -> bool:
        """Return True if *severity* meets or exceeds the configured threshold."""
        threshold = self._config.security_patch_severity_threshold
        alert_rank = _SEVERITY_RANK.get(severity.lower(), 99)
        threshold_rank = _SEVERITY_RANK.get(threshold.lower(), 1)
        return alert_rank <= threshold_rank

    @staticmethod
    def _is_fixable(alert: dict) -> bool:
        """Return True if the alert has a patched version with a known identifier."""
        vuln = alert.get("security_vulnerability") or {}
        patched = vuln.get("first_patched_version")
        if patched is None:
            return False
        if isinstance(patched, dict):
            return bool(patched.get("identifier"))
        return bool(patched)

    @staticmethod
    def _extract_info(alert: dict) -> tuple[str, str, str]:
        """Extract (package_name, severity, advisory_summary) from an alert."""
        vuln = alert.get("security_vulnerability") or {}
        pkg = vuln.get("package", {}).get("name", "unknown")
        severity = vuln.get("severity", "unknown")
        advisory = alert.get("security_advisory") or {}
        summary = advisory.get("summary", "Security vulnerability")
        return pkg, severity, summary

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.security_patch_loop_enabled:
            return {"status": "config_disabled"}

        if self._config.dry_run:
            return None

        rollup = self._rollups()
        alerts = await self._pr_manager.get_dependabot_alerts(state="open")

        filed = 0
        skipped_dedup = 0
        skipped_unfixable = 0
        skipped_severity = 0

        for alert in alerts:
            alert_key = str(alert.get("number", ""))
            if not alert_key:
                continue

            # Skip unfixable alerts
            if not self._is_fixable(alert):
                skipped_unfixable += 1
                continue

            pkg, severity, summary = self._extract_info(alert)

            # Skip alerts below severity threshold
            if not self._meets_severity(severity):
                skipped_severity += 1
                continue

            title = f"[Security] {summary} in {pkg}"
            body = (
                f"## Dependabot Alert #{alert_key}\n\n"
                f"**Package:** {pkg}\n"
                f"**Severity:** {severity}\n"
                f"**Summary:** {summary}\n\n"
                f"A patched version is available. Please update the dependency.\n"
            )

            # ensure() creates one issue per alert and is a no-op when it is
            # already tracked (or already open on GitHub by title) — so the old
            # local-dedup + find_existing_issue backstop are both internal now.
            already = (
                self._state.get_rollup_issue(f"security_patch:{alert_key}") is not None
            )
            await rollup.ensure(alert_key, title=title, body=body)
            if already:
                skipped_dedup += 1
            else:
                filed += 1
                logger.info(
                    "Filed security issue for alert #%s: %s in %s (%s)",
                    alert_key,
                    summary,
                    pkg,
                    severity,
                )

        closed = await self._close_resolved(rollup)

        return {
            "total_alerts": len(alerts),
            "filed": filed,
            "closed": closed,
            "skipped_dedup": skipped_dedup,
            "skipped_unfixable": skipped_unfixable,
            "skipped_severity": skipped_severity,
        }

    async def _close_resolved(self, rollup: RollupIssueManager) -> int:
        """Close security issues for alerts GitHub now reports as resolved (#9359).

        Queries the resolved alert states explicitly (``fixed`` / ``dismissed``
        / ``auto_dismissed``) and ``resolve``\\ s only the tracked subjects in
        that set. ``resolve`` is a no-op for an untracked alert, so this never
        touches an issue we did not file, and a failed (``[]``) query closes
        nothing — sidestepping the mass-close hazard of an open-set reconcile.
        """
        resolved_keys: set[str] = set()
        for resolved_state in _RESOLVED_STATES:
            for alert in await self._pr_manager.get_dependabot_alerts(
                state=resolved_state
            ):
                key = str(alert.get("number", ""))
                if key:
                    resolved_keys.add(key)

        closed = 0
        for key in sorted(resolved_keys):
            if await rollup.resolve(
                key,
                comment=(
                    "Dependabot alert resolved — auto-closing security issue (#9359)."
                ),
            ):
                closed += 1
                logger.info("Closed security issue for resolved alert #%s", key)
        return closed
