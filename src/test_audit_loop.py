"""Background worker loop — run test audits and file issues for quality findings."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from agent_cli import build_agent_command
from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import Credentials, HydraFlowConfig
from dedup_store import DedupStore
from runner_utils import stream_claude_process

if TYPE_CHECKING:
    from ports import PRPort

logger = logging.getLogger("hydraflow.test_audit_loop")

# Severities that warrant filing an issue.
_ACTIONABLE_SEVERITIES = frozenset({"critical", "high"})


class TestAuditLoop(BaseBackgroundLoop):
    """Periodically runs full test audits and files issues for quality findings.

    Invokes the Claude CLI with the ``/hf.audit-tests`` skill, parses
    the output for structured findings, and files GitHub issues for any
    critical or high severity items.  Uses :class:`DedupStore` to avoid
    filing duplicate issues for the same finding.
    """

    _FINDING_RE = re.compile(
        r"\{[^{}]*\"id\"\s*:\s*\"[^\"]+\"[^{}]*\}",
        re.DOTALL,
    )

    def __init__(
        self,
        config: HydraFlowConfig,
        pr_manager: PRPort,
        deps: LoopDeps,
        credentials: Credentials | None = None,
    ) -> None:
        super().__init__(worker_name="test_audit", config=config, deps=deps)
        self._pr_manager = pr_manager
        self._credentials = credentials or Credentials()
        self._dedup = DedupStore(
            "test_audit_findings",
            config.data_root / "memory" / "test_audit_dedup.json",
        )

    def _get_default_interval(self) -> int:
        return self._config.test_audit_interval

    async def _run_audit(self) -> list[dict]:
        """Run the test audit skill and return parsed findings."""
        cmd = build_agent_command(
            tool=self._config.background_tool
            if self._config.background_tool != "inherit"
            else "claude",
            model=self._config.background_model or "sonnet",
            max_turns=10,
        )

        transcript = await stream_claude_process(
            cmd=cmd,
            prompt="/hf.audit-tests",
            cwd=self._config.repo_root,
            active_procs=set(),
            event_bus=self._bus,
            event_data={"source": "test_audit"},
            logger=logger,
            gh_token=self._credentials.gh_token,
        )

        return self._parse_findings(transcript)

    @classmethod
    def _parse_findings(cls, transcript: str) -> list[dict]:
        """Extract structured finding dicts from audit transcript."""
        findings: list[dict] = []
        for match in cls._FINDING_RE.finditer(transcript):
            try:
                obj = json.loads(match.group(0))
                if isinstance(obj, dict) and "id" in obj and "severity" in obj:
                    findings.append(obj)
            except (json.JSONDecodeError, TypeError):
                continue
        return findings

    async def _do_work(self) -> dict[str, Any] | None:
        if self._config.dry_run:
            return None

        try:
            findings = await self._run_audit()
        except Exception:
            logger.warning("Test audit failed", exc_info=True)
            return {"filed": 0, "error": True}

        seen = self._dedup.get()
        filed = 0
        skipped_dedup = 0
        skipped_severity = 0

        for finding in findings:
            finding_id = finding.get("id", "")
            if not finding_id:
                continue

            if finding_id in seen:
                skipped_dedup += 1
                continue

            severity = finding.get("severity", "").lower()
            if severity not in _ACTIONABLE_SEVERITIES:
                skipped_severity += 1
                continue

            title = f"[Test Audit] {finding.get('title', 'Test quality finding')}"
            body = (
                f"## Test Quality Finding\n\n"
                f"**ID:** {finding_id}\n"
                f"**Severity:** {severity}\n\n"
                f"### Description\n\n"
                f"{finding.get('description', 'No description available.')}\n"
            )

            await self._pr_manager.create_issue(title, body, labels=["test-quality"])
            self._dedup.add(finding_id)
            filed += 1

            logger.info(
                "Filed test audit issue: %s (%s)",
                finding_id,
                severity,
            )

        return {
            "total_findings": len(findings),
            "filed": filed,
            "skipped_dedup": skipped_dedup,
            "skipped_severity": skipped_severity,
        }
