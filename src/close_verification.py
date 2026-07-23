"""Close-verification controller (#10358) — reopen + re-triage a false auto-close.

The G3 *actuator* half of the close-verification control loop. #10356 shipped
the P10.7 *detector*: a history scan that FLAGS an issue closed by a PR
carrying neither a non-test source change nor a ``tests/regressions/`` delta
(the #10223 false-close signature, with a ``Skip-Regression:`` opt-out). The
detector *measures* the open loop; it does not *close* it. This module closes
it: a post-merge OBSERVER that, when the just-merged PR that closed an issue
matches the SAME signature, REOPENS the issue and re-triages it (re-applies
``find_label``) so a delta-less "done" is actually driven to a fix.

Why the observer form (not per-call-site guards): GitHub auto-closes on
``Closes #N`` at merge and the explicit ``close_issue`` call sites are
scattered across the loop layer, so there is no single clean pre-close choke
point. Reopening after the fact is one place, testable with a fake PRPort, and
can never wedge a legitimate close.

Reuses the P10.7 classifier verbatim (``src/false_close.py``, imported by both
this controller and ``scripts/hydraflow_audit/checks/p10_tdd.py``) so the sensor
and the actuator can never disagree on what "false close" means, honouring the
identical ``Skip-Regression:`` opt-out. The classifier lives in ``src`` — never
``scripts`` — because the container runs ``PYTHONPATH=src`` and ``src`` must not
import from ``scripts`` (see #10365).

Default-OFF behind ``config.close_verification_enabled``
(``HYDRAFLOW_CLOSE_VERIFICATION_ENABLED``, default false): fully inert — makes
no port calls and changes no behaviour — until enabled, exactly like the G1
auto-recut actuator.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from events import EventBus, EventType, HydraFlowEvent
from exception_classify import reraise_on_credit_or_bug
from false_close import has_skip_regression, is_false_close
from models import SystemAlertPayload

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from ports import PRPort

logger = logging.getLogger("hydraflow.close_verification")


@dataclass(frozen=True)
class CloseVerificationResult:
    """Outcome of a close-verification pass over one merged PR.

    ``actuated`` is True only when the issue was actually reopened + re-triaged.
    ``reason`` is a short, greppable tag for observability/telemetry:
    ``"disabled"``, ``"skip-regression"``, ``"fix-delta-present"``, or
    ``"reopened"``.
    """

    actuated: bool
    reason: str


async def reconcile_false_close(
    *,
    config: HydraFlowConfig,
    prs: PRPort,
    issue_number: int,
    pr_number: int,
    bus: EventBus | None = None,
) -> CloseVerificationResult:
    """Reopen + re-triage *issue_number* when the merged PR *pr_number* is a false close.

    Runs after the merge path has already closed *issue_number*. Returns
    without touching GitHub when:

    * the controller is disabled (``close_verification_enabled`` false) —
      the very first check, so the OFF path makes no port calls at all;
    * the PR's diff carries a fix delta (``tests/regressions/`` or non-test
      product source); or
    * a ``Skip-Regression:`` opt-out trailer justifies the close.

    Otherwise it reopens the issue, swaps it back to ``find_label`` (the
    canonical re-triage re-entry ``TriagePhase`` polls), posts an explanatory
    comment, and — when a *bus* is provided — publishes a SYSTEM_ALERT so the
    dashboard surfaces the self-correction.

    Fail-soft: any error is logged and swallowed (a hygiene reconciler must
    never blow up the merge path) EXCEPT credit-exhaustion / bug signals,
    which are re-raised via ``reraise_on_credit_or_bug``.
    """
    if not config.close_verification_enabled:
        return CloseVerificationResult(actuated=False, reason="disabled")

    try:
        paths = await prs.get_pr_diff_names(pr_number)
        message = await prs.get_pr_commit_messages(pr_number)
        if not is_false_close(paths, message):
            # A real fix delta landed, or a Skip-Regression: trailer opted the
            # close out. is_false_close folds both; disambiguate for telemetry.
            reason = (
                "skip-regression"
                if has_skip_regression(message)
                else "fix-delta-present"
            )
            return CloseVerificationResult(actuated=False, reason=reason)

        await prs.reopen_issue(issue_number)
        await prs.swap_pipeline_labels(issue_number, config.find_label[0])
        await prs.post_comment(
            issue_number,
            _reopen_comment(pr_number),
        )
        if bus is not None:
            await bus.publish(
                HydraFlowEvent(
                    type=EventType.SYSTEM_ALERT,
                    data=SystemAlertPayload(
                        message=(
                            f"Close-verification reopened issue #{issue_number}: "
                            f"PR #{pr_number} closed it without a fix delta "
                            "(the #10223 false-close signature). Re-triaged for "
                            "a real fix."
                        ),
                        source="close_verification",
                        severity="warning",
                        issue=issue_number,
                    ),
                )
            )
        logger.info(
            "close_verification: reopened + re-triaged #%d (false close by PR #%d)",
            issue_number,
            pr_number,
        )
        return CloseVerificationResult(actuated=True, reason="reopened")
    except (RuntimeError, OSError, ValueError) as exc:
        # Fail-soft: a hygiene reconciler must never blow up the merge path.
        # reraise_on_credit_or_bug still lets a credit-exhaustion signal (a
        # RuntimeError subclass) or a likely bug propagate; real programming
        # errors (Attribute/Type/KeyError) fall outside this catch and surface.
        reraise_on_credit_or_bug(exc)
        logger.warning(
            "close_verification: reconcile failed for issue #%d (PR #%d)",
            issue_number,
            pr_number,
            exc_info=True,
        )
        return CloseVerificationResult(actuated=False, reason="error")


def _reopen_comment(pr_number: int) -> str:
    """The explanatory comment posted on a reopened false-close issue."""
    return (
        "**Reopened by close-verification (#10358).**\n\n"
        f"PR #{pr_number} closed this issue but its diff carried no fix delta "
        "— neither a non-test source change nor a `tests/regressions/` test "
        '(the #10223 false-close signature). "Done" was emitted with nothing '
        "that could have fixed the bug, so the issue is reopened and "
        "re-triaged to drive a real fix.\n\n"
        "If the fix legitimately landed elsewhere, close again with a "
        "`Skip-Regression: <why>` trailer on the closing commit.\n\n"
        "---\n*HydraFlow close-verification controller*"
    )
