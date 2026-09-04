"""Runs the artifact-chain gate at the merge seam (ADR-0149 P4).

The gate itself (:mod:`change_chain_gate`) is pure: it takes a record, the
files a PR touched, and the charter's requirement, and returns findings.
This module is the impure half — it locates the change's worktree, asks git
for the changed paths, reads the anchor and the charter, and reports what
came back.

**Report-only, by design.** ADR-0149 P4 stages this the way vitals and
setpoints were staged: findings are posted and counted, never merged on.
Nothing here returns a verdict the caller can fail a merge with, and that
is deliberate — wiring it to block is a separate, later decision with its
own evidence.

Never raises into the merge path. A gate that cannot run reports nothing
rather than killing a merge — but "cannot run" is reported as its own
finding, because a silent gate and a clean change look identical and this
repo has shipped that confusion before.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from change_chain_gate import ChainFinding, verify_chain
from change_chain_recorder import latest_record
from charter import load_charter

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from ports import PRPort

logger = logging.getLogger(__name__)

COMMENT_HEADING = "## Artifact chain (ADR-0149) — report only"

#: Emitted when the gate could not establish what the PR touched. Distinct
#: from "the scope was clean": `get_pr_diff_names` returning nothing is
#: ambiguous between an empty PR and a `gh` failure, and reporting the
#: ambiguity as cleanliness is the failure mode change_chain's own docstring
#: names — a gate that stops seeing its subject reads exactly like a pass.
FINDING_UNVERIFIABLE = "chain-unverifiable"


def _required_artifacts(config: HydraFlowConfig) -> tuple[str, ...]:
    """The charter's ``artifacts.chain`` declaration, or () when unreadable.

    Delegates to :func:`charter.load_charter`, which already handles a
    missing file, a non-mapping charter and the legacy fallback. Hand-rolling
    the read here dropped all three and hardcoded the filename.
    """
    try:
        charter = load_charter(config.repo_root)
    except Exception:
        logger.debug("charter unreadable — chain gate requires nothing")
        return ()
    return charter.artifacts.chain if charter is not None else ()


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
            "(ADR-0149 P4) until its findings have been judged._",
        ]
    )
    return "\n".join(lines)


async def _already_reported(prs: PRPort, pr_number: int) -> bool:
    """True when a chain report is already on this PR.

    ``handle_approved`` re-runs on retries — a policy denial, a conflict
    that gets resolved and re-reviewed, any re-queue after escalation — and
    without this each pass posts an identical comment.
    """
    try:
        comments = await prs.list_issue_comments(pr_number)
    except Exception:
        return False
    return any(COMMENT_HEADING in str(comment.get("body", "")) for comment in comments)


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
        if record is None:
            # No anchor at all. Most often this is a change that never went
            # through the plan phase — a wiki/diagram/arch self-maintenance
            # PR — which the chain was never meant to cover. Reporting
            # `chain-absent` on those would put a comment on every bot merge.
            logger.info(
                "No chain anchor for issue #%d (PR #%d) — nothing to verify",
                issue_number,
                pr_number,
                extra={"issue": issue_number},
            )
            return ()

        # The change's OWN worktree, not the factory's main checkout. The
        # chain is committed to the PR branch and this runs before the merge,
        # so repo_root has none of it — verifying there reported
        # `chain-artifact-missing` on every single PR and never reached the
        # digest or scope checks at all.
        worktree = config.workspace_path_for_issue(issue_number)

        changed = tuple(await prs.get_pr_diff_names(pr_number))
        if not changed:
            return (
                ChainFinding(
                    FINDING_UNVERIFIABLE,
                    f"could not establish which files PR #{pr_number} touched, "
                    "so the scope of this change was not checked",
                ),
            )

        findings = verify_chain(
            worktree,
            issue_number,
            record,
            changed,
            required=_required_artifacts(config),
        )
    except Exception:
        # Broad on purpose: this is an advisory observer sitting in the merge
        # path, and anything it can raise must cost the change its report,
        # never its merge. It is REPORTED rather than swallowed silently —
        # a gate that errored and a gate that found nothing must not look
        # the same to whoever judges the staged rollout.
        logger.warning(
            "Chain gate errored for issue #%d (PR #%d)",
            issue_number,
            pr_number,
            exc_info=True,
            extra={"issue": issue_number},
        )
        findings = (
            ChainFinding(
                FINDING_UNVERIFIABLE,
                "the chain gate raised while verifying this change; its "
                "chain was not checked",
            ),
        )

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
        if not await _already_reported(prs, pr_number):
            await prs.post_pr_comment(
                pr_number, format_findings(issue_number, findings)
            )
    except Exception:
        logger.warning(
            "Could not post the chain report for PR #%d", pr_number, exc_info=True
        )
    return findings
