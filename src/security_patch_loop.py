"""Background worker loop — auto-patch Dependabot security alerts."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig

if TYPE_CHECKING:
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.security_patch_loop")


class SecurityPatchLoop(BaseBackgroundLoop):
    """Polls Dependabot alerts and triggers fixes for matching severities."""

    def __init__(
        self,
        config: HydraFlowConfig,
        prs: PRManager,
        state: StateTracker,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="security_patch", config=config, deps=deps)
        self._prs = prs
        self._state = state

    def _get_default_interval(self) -> int:
        return self._config.security_patch_interval

    async def _do_work(self) -> dict[str, Any] | None:
        """Check Dependabot alerts and trigger fixes for matching severities."""
        settings = self._state.get_security_patch_settings()
        processed = self._state.get_security_patch_processed()
        severity_set = {s.lower() for s in settings.severity_levels}

        alerts = await self._fetch_alerts()

        triggered = 0
        skipped = 0
        manual_issues = 0

        for alert in alerts:
            alert_id = str(alert.get("number", ""))
            severity = alert.get("security_advisory", {}).get("severity", "").lower()

            # Skip already-processed alerts
            if alert_id in processed:
                skipped += 1
                continue

            # Skip alerts not matching configured severity
            if severity not in severity_set:
                skipped += 1
                continue

            # Skip alerts that already have a fix
            if self._has_existing_pr(alert):
                skipped += 1
                continue

            # Try to trigger Dependabot auto-fix
            fix_triggered = await self._trigger_fix(alert)
            if fix_triggered:
                triggered += 1
                self._state.add_security_patch_processed(alert_id)
                logger.info(
                    "Triggered Dependabot fix for alert #%s (%s)",
                    alert_id,
                    severity,
                )
            else:
                # Dependabot can't auto-fix — create a manual issue
                await self._create_manual_issue(alert)
                manual_issues += 1
                self._state.add_security_patch_processed(alert_id)
                logger.info(
                    "Created manual issue for alert #%s (%s)",
                    alert_id,
                    severity,
                )

        # Emit Sentry breadcrumb
        self._emit_sentry_breadcrumb(triggered, skipped, manual_issues)

        return {
            "triggered": triggered,
            "skipped": skipped,
            "manual_issues": manual_issues,
        }

    async def _fetch_alerts(self) -> list[dict[str, Any]]:
        """Fetch open Dependabot alerts via gh api."""
        repo = self._config.repo
        if not repo:
            logger.warning("No repo configured — skipping security patch check")
            return []
        try:
            raw = await self._prs._run_gh(
                "gh",
                "api",
                f"repos/{repo}/dependabot/alerts?state=open",
            )
            result = json.loads(raw)
            if isinstance(result, list):
                return result
        except Exception:  # noqa: BLE001
            logger.debug("Failed to fetch Dependabot alerts", exc_info=True)
        return []

    def _has_existing_pr(self, alert: dict[str, Any]) -> bool:
        """Check if the alert already has a fix (fixed_at is set)."""
        return alert.get("fixed_at") is not None

    async def _trigger_fix(self, alert: dict[str, Any]) -> bool:
        """Comment on the alert to trigger Dependabot auto-fix.

        Returns True if the comment was posted successfully.
        """
        alert_number = alert.get("number")
        if alert_number is None:
            return False
        try:
            repo = self._config.repo
            await self._prs._run_gh(
                "gh",
                "api",
                f"repos/{repo}/issues/{alert_number}/comments",
                "-f",
                "body=@dependabot create fix",
            )
            return True
        except Exception:  # noqa: BLE001
            logger.debug(
                "Failed to trigger Dependabot fix for alert #%s",
                alert_number,
                exc_info=True,
            )
            return False

    async def _create_manual_issue(self, alert: dict[str, Any]) -> None:
        """Create a GitHub issue for manual fixing of a security alert."""
        alert_number = alert.get("number", "?")
        severity = alert.get("security_advisory", {}).get("severity", "unknown")
        pkg = alert.get("dependency", {}).get("package", {})
        pkg_name = pkg.get("name", "unknown")
        ecosystem = pkg.get("ecosystem", "unknown")

        title = f"[Security] Fix {severity} vulnerability in {pkg_name} ({ecosystem})"
        body = (
            f"## Security Alert #{alert_number}\n\n"
            f"**Severity:** {severity}\n"
            f"**Package:** {pkg_name} ({ecosystem})\n\n"
            f"Dependabot was unable to create an automatic fix for this alert. "
            f"Manual intervention is required.\n\n"
            f"See: https://github.com/{self._config.repo}/security/dependabot/{alert_number}"
        )
        await self._prs.create_task(title, body)

    @staticmethod
    def _emit_sentry_breadcrumb(
        triggered: int, skipped: int, manual_issues: int
    ) -> None:
        """Emit a Sentry breadcrumb summarizing the cycle."""
        try:
            import sentry_sdk  # noqa: PLC0415

            sentry_sdk.add_breadcrumb(
                category="security_patch",
                message=f"Security patch cycle: {triggered} triggered, {skipped} skipped, {manual_issues} manual",
                level="info",
                data={
                    "triggered": triggered,
                    "skipped": skipped,
                    "manual_issues": manual_issues,
                },
            )
        except ImportError:
            pass
