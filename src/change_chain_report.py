"""Runs the artifact-chain gate at the merge seam (ADR-0149 P4).

The gate itself (:mod:`change_chain_gate`) is pure: it takes a record, the
files a PR touched, and the charter's requirement, and returns findings.
This module is the impure half — it fetches the diff, reads the anchor and
the charter, and reports what came back.

**Report-only, by design.** ADR-0149 P4 stages this the way vitals and
setpoints were staged: findings are posted and counted, never merged on.
The scope check in particular reads plan prose with a regex and will
produce false positives; the whole point of the staged rollout is to
measure that rate before anything is allowed to block on it. Nothing here
returns a verdict the caller can fail a merge with, and that is deliberate
— wiring it to block is a separate, later decision with its own evidence.

Never raises into the merge path. A gate that cannot run is a gate that
reports nothing, not a merge that dies.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from change_chain_gate import ChainFinding, verify_chain
from change_chain_recorder import latest_record

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from ports import PRPort

logger = logging.getLogger(__name__)

#: `+++ b/path` in a unified diff. `/dev/null` marks a deletion's b-side.
_DIFF_TARGET = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)

COMMENT_HEADING = "## Artifact chain (ADR-0149) — report only"


def changed_files_from_diff(diff: str) -> tuple[str, ...]:
    """Extract the changed paths from a unified diff.

    Reads the ``+++ b/`` side, so a pure deletion (``+++ /dev/null``) is
    skipped: the scope check asks which files a change *touched*, and a
    removed file has no post-image path to compare against the plan.
    """
    return tuple(
        path.strip()
        for path in _DIFF_TARGET.findall(diff)
        if path.strip() and path.strip() != "/dev/null"
    )


def _required_artifacts(config: HydraFlowConfig) -> tuple[str, ...]:
    """The charter's ``artifacts.chain`` declaration, or () when unreadable.

    Read per call rather than cached: the charter is an operator-edited file
    and this runs once per merge, so a stale read would silently apply the
    previous declaration to every subsequent change.
    """
    try:
        import yaml

        from charter_model import Charter

        raw = (config.repo_root / "charter.yaml").read_text(encoding="utf-8")
        return Charter.from_dict(yaml.safe_load(raw)).artifacts.chain
    except (OSError, ValueError, ImportError):
        logger.debug("charter.yaml unreadable — chain gate requires nothing")
        return ()


def format_findings(issue_number: int, findings: tuple[ChainFinding, ...]) -> str:
    """Render findings as a PR comment body."""
    lines = [
        COMMENT_HEADING,
        "",
        f"The committed chain for issue #{issue_number} was compared against "
        "its anchored digests on the CH-1 `change_chain` stream.",
        "",
    ]
    lines.extend(f"- **{finding.code}** — {finding.detail}" for finding in findings)
    lines.extend(
        [
            "",
            "_This gate does not block a merge. It is staged report-only "
            "(ADR-0149 P4) until its findings have been judged — the scope "
            "check reads plan prose with a regex and is expected to produce "
            "false positives._",
        ]
    )
    return "\n".join(lines)


async def report_chain_findings(
    *,
    config: HydraFlowConfig,
    prs: PRPort,
    pr_number: int,
    issue_number: int,
) -> tuple[ChainFinding, ...]:
    """Verify *issue_number*'s committed chain and report. Never blocks.

    Returns the findings so a caller can count them; the merge path ignores
    the value beyond logging.
    """
    if not config.change_chain_enabled:
        return ()

    try:
        record = latest_record(config, issue_number)
        diff = await prs.get_pr_diff(pr_number)
        findings = verify_chain(
            config.repo_root,
            issue_number,
            record,
            changed_files_from_diff(diff),
            required=_required_artifacts(config),
        )
    except Exception:
        # Broad on purpose, and it does not re-raise: this is an advisory
        # observer sitting in the merge path. Anything it can raise —
        # a port error, a malformed record, a diff it cannot parse — must
        # cost the change its chain report, never its merge.
        logger.warning(
            "Chain gate could not run for issue #%d (PR #%d) — no report",
            issue_number,
            pr_number,
            exc_info=True,
            extra={"issue": issue_number},
        )
        return ()

    if not findings:
        logger.info(
            "Chain gate clean for issue #%d (PR #%d)",
            issue_number,
            pr_number,
            extra={"issue": issue_number},
        )
        return ()

    logger.warning(
        "Chain gate: %d finding(s) for issue #%d (PR #%d): %s",
        len(findings),
        issue_number,
        pr_number,
        ", ".join(sorted({finding.code for finding in findings})),
        extra={"issue": issue_number},
    )
    try:
        await prs.post_comment(pr_number, format_findings(issue_number, findings))
    except Exception:
        logger.warning(
            "Could not post the chain report for PR #%d", pr_number, exc_info=True
        )
    return findings
