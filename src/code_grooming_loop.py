"""Background worker loop — periodic code audits that file prioritized improvement issues."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from models import AuditFinding

if TYPE_CHECKING:
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.code_grooming_loop")

# Priority ordering for filtering
_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def _meets_min_priority(finding_priority: str, min_priority: str) -> bool:
    """Return True if *finding_priority* is at or above *min_priority*."""
    return _PRIORITY_ORDER.get(finding_priority, 99) <= _PRIORITY_ORDER.get(
        min_priority, 99
    )


async def _run_audit(audit_name: str, repo_root: str) -> list[AuditFinding]:
    """Run a single audit tool and parse findings.

    Uses ``asyncio.create_subprocess_exec`` (never ``shell=True``) to avoid
    command-injection risks — all arguments are passed as a list.
    """
    findings: list[AuditFinding] = []

    if audit_name == "lint":
        try:
            proc = await asyncio.create_subprocess_exec(
                "ruff",
                "check",
                "--output-format=json",
                repo_root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if stdout:
                for item in json.loads(stdout):
                    findings.append(
                        AuditFinding(
                            category="lint",
                            priority="P2",
                            summary=f"{item.get('code', 'unknown')}: {item.get('message', '')}",
                            file_path=item.get("filename", ""),
                            details=item.get("message", ""),
                        )
                    )
        except (FileNotFoundError, json.JSONDecodeError):
            logger.debug("ruff not available or output parse error")

    elif audit_name == "dead_code":
        try:
            proc = await asyncio.create_subprocess_exec(
                "vulture",
                repo_root,
                "--min-confidence=80",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if stdout:
                for line in stdout.decode().strip().splitlines():
                    findings.append(
                        AuditFinding(
                            category="dead_code",
                            priority="P3",
                            summary=line.strip(),
                            file_path=line.split(":")[0] if ":" in line else "",
                        )
                    )
        except FileNotFoundError:
            logger.debug("vulture not available")

    elif audit_name == "complexity":
        try:
            proc = await asyncio.create_subprocess_exec(
                "ruff",
                "check",
                "--select=C901",
                "--output-format=json",
                repo_root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if stdout:
                for item in json.loads(stdout):
                    findings.append(
                        AuditFinding(
                            category="complexity",
                            priority="P1",
                            summary=f"High complexity: {item.get('message', '')}",
                            file_path=item.get("filename", ""),
                            details=item.get("message", ""),
                        )
                    )
        except (FileNotFoundError, json.JSONDecodeError):
            logger.debug("ruff complexity check failed")

    return findings


class CodeGroomingLoop(BaseBackgroundLoop):
    """Runs configured audit checks, classifies findings, and files issues."""

    def __init__(
        self,
        config: HydraFlowConfig,
        prs: PRManager,
        state: StateTracker,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="code_grooming", config=config, deps=deps)
        self._prs = prs
        self._state = state

    def _get_default_interval(self) -> int:
        return self._config.code_grooming_interval

    async def _do_work(self) -> dict[str, Any] | None:
        """Execute one grooming cycle."""
        settings = self._state.get_code_grooming_settings()
        already_filed = self._state.get_code_grooming_filed()

        stats: dict[str, int] = {"scanned": 0, "filed": 0, "skipped": 0}

        # Collect findings from all enabled audits
        all_findings: list[AuditFinding] = []
        for audit in settings.enabled_audits:
            try:
                findings = await _run_audit(audit, str(self._config.repo_root))
                all_findings.extend(findings)
            except Exception:
                logger.exception("Audit %s failed", audit)

        stats["scanned"] = len(all_findings)

        # Filter by priority
        eligible = [
            f
            for f in all_findings
            if _meets_min_priority(f.priority, settings.min_priority)
        ]

        # Deduplicate against already-filed
        new_findings = [
            f for f in eligible if f"{f.category}:{f.summary}" not in already_filed
        ]

        # Also deduplicate against open issues to avoid re-filing
        open_issue_titles: set[str] = set()
        try:
            raw = await self._prs._run_gh(
                "gh",
                "issue",
                "list",
                "--repo",
                self._prs._repo,
                "--state",
                "open",
                "--limit",
                "200",
                "--json",
                "title",
            )
            if raw:
                open_issue_titles = {item.get("title", "") for item in json.loads(raw)}
        except Exception:
            logger.debug("Failed to fetch open issues for dedup")

        filed_count = 0
        for finding in new_findings:
            if filed_count >= settings.max_issues_per_cycle:
                break

            title = f"[Code Grooming] [{finding.priority}] {finding.summary[:80]}"
            if title in open_issue_titles:
                stats["skipped"] += 1
                continue

            if settings.dry_run:
                logger.info("[dry-run] Would file: %s", title)
                filed_count += 1
                stats["filed"] += 1
                continue

            body = (
                f"## Code Grooming Finding\n\n"
                f"**Category:** {finding.category}\n"
                f"**Priority:** {finding.priority}\n"
                f"**File:** `{finding.file_path}`\n\n"
                f"### Details\n{finding.details or finding.summary}\n\n"
                f"*Filed automatically by HydraFlow Code Grooming.*"
            )

            try:
                await self._prs._run_gh(
                    "gh",
                    "issue",
                    "create",
                    "--repo",
                    self._prs._repo,
                    "--title",
                    title,
                    "--body",
                    body,
                )
                key = f"{finding.category}:{finding.summary}"
                self._state.add_code_grooming_filed(key)
                filed_count += 1
                stats["filed"] += 1
                logger.info("Filed grooming issue: %s", title)
            except Exception:
                logger.exception("Failed to file grooming issue: %s", title)

        try:
            import sentry_sdk as _sentry

            _sentry.add_breadcrumb(
                category="code_grooming.cycle",
                message=f"Scanned {stats['scanned']} findings, filed {stats['filed']}",
                level="info",
                data=stats,
            )
        except ImportError:
            pass

        return stats
