"""Caretaker loop: audit live branch protection against the canonical rulesets.

The runtime enforcer for ADR-0082. Periodically compares live GitHub branch
protection to the rulesets generated from
``docs/standards/branch_protection/gates.toml`` and files one issue per distinct
drift signature (deduped) so the standard cannot silently outrun reality.
Follows ADR-0029 (caretaker pattern) and ADR-0049 (kill-switch).
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from exception_classify import reraise_on_credit_or_bug

if TYPE_CHECKING:
    from branch_protection_audit import AuditReport
    from dedup_store import DedupStore
    from ports import PRPort

logger = logging.getLogger("hydraflow.branch_protection_auditor")

_DRIFT_LABELS = ["hydraflow-find", "hydraflow-branch-protection-drift"]


def _drift_key(report: AuditReport) -> str:
    """Stable dedup key for a drift signature (same drift => no re-file)."""
    digest = hashlib.sha256("\n".join(report.drifts).encode()).hexdigest()
    return f"branch_protection_auditor:{report.repo}:{digest[:16]}"


def _issue_body(report: AuditReport) -> str:
    drift = "\n".join(report.drifts)
    return (
        "## Branch-protection ruleset drift\n\n"
        f"Live GitHub branch protection on `{report.repo}` diverges from the "
        "canonical rulesets generated from "
        "`docs/standards/branch_protection/gates.toml` (ADR-0082).\n\n"
        f"```\n{drift}\n```\n\n"
        "Reconcile (regenerate from the contract, then re-apply):\n\n"
        "```bash\n"
        "make gen-gates\n"
        "python scripts/setup_branch_protection.py --apply\n"
        "```\n\n"
        "Then confirm with `python scripts/setup_branch_protection.py --audit`."
    )


class BranchProtectionAuditorLoop(BaseBackgroundLoop):
    """Files an issue when live branch protection drifts from the contract.

    Caretaker loop for ADR-0082 (declarative gate contract); follows ADR-0029
    (caretaker pattern) and ADR-0049 (kill-switch convention).
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        pr_manager: PRPort,
        dedup: DedupStore,
        deps: LoopDeps,
        *,
        auditor: Callable[[], Awaitable[AuditReport]],
    ) -> None:
        super().__init__(
            worker_name="branch_protection_auditor", config=config, deps=deps
        )
        self._prs = pr_manager
        self._dedup = dedup
        self._auditor = auditor

    def _get_default_interval(self) -> int:
        return self._config.branch_protection_auditor_interval

    async def _do_work(self) -> dict[str, Any] | None:  # noqa: PLR0911
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.branch_protection_auditor_loop_enabled:
            return {"status": "config_disabled"}
        if self._config.dry_run:
            return None

        try:
            report = await self._auditor()
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("branch-protection audit failed", exc_info=True)
            return {"error": True}

        if report.clean:
            # Drift resolved — close the open drift issue and clear the dedup so
            # a future drift re-files (#9359 issue-hygiene). The dedup store is
            # dedicated to this loop, so clearing it is safe.
            await self._resolve_drift_issue(report.repo)
            return {"status": "clean"}

        key = _drift_key(report)
        if key in self._dedup.get():
            return {"status": "drift", "deduped": True}

        try:
            issue = await self._prs.create_issue(
                f"[branch-protection] ruleset drift on {report.repo}",
                _issue_body(report),
                labels=_DRIFT_LABELS,
            )
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "could not file branch-protection drift issue", exc_info=True
            )
            return {"status": "drift", "error": True}

        if issue == 0:
            logger.error(
                "branch-protection auditor: create_issue returned 0 (sentinel) — "
                "not tracking phantom issue; will retry next cycle"
            )
            return {"status": "drift", "error": True}

        self._dedup.add(key)
        logger.info(
            "branch-protection auditor: filed issue #%d for ruleset drift", issue
        )
        return {"status": "drift", "issue_created": issue}

    async def _resolve_drift_issue(self, repo: str) -> None:
        """Close the open ruleset-drift issue and clear the dedup on recovery."""
        title = f"[branch-protection] ruleset drift on {repo}"
        existing = await self._prs.find_existing_issue(title)
        if existing:
            await self._prs.post_comment(
                existing,
                "Branch-protection ruleset drift resolved — auto-closing.",
            )
            await self._prs.close_issue(existing)
        if self._dedup.get():
            self._dedup.set_all(set())
