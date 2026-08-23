"""Label-drift detection surface of ``FakeGitHub``.

Extracted VERBATIM from ``src/mockworld/fakes/fake_github.py``
(god-class decomposition, Refs #11547) as a mixin. ``FakeGitHub`` inherits it,
so every method here still resolves as an attribute of ``FakeGitHub`` and every
seam that drives the fake through a Port resolves to the same object as before.

The cluster boundary mirrors the real adapter's: this module is the fake's
side of ``pr_manager_drift.PRManagerDriftMixin``, so the fake and the thing it doubles read alike.

One concern: the ADR-0088 reconciliation reads — issue/PR label drift, closed
issues still carrying a dispatchable stage label, and the open PR that already
resolves an issue.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from models import ClosedStageLabelDrift, LabelDrift

from ._common import _DISPATCHABLE_STAGE_LABELS

if TYPE_CHECKING:
    from ._common import FakeIssue, FakePR


class FakeGitHubDriftMixin:
    """Label-drift detection surface of ``FakeGitHub``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``FakeGitHub.__init__`` or by
    # a sibling mixin. The method declarations are TYPE_CHECKING-only
    # on purpose: a runtime ``...`` body would win over the
    # real implementation whenever this mixin precedes the
    # implementing one in ``FakeGitHub``'s MRO.
    # ------------------------------------------------------------------
    _issues: dict[int, FakeIssue]
    _prs: dict[int, FakePR]

    if TYPE_CHECKING:

        def _maybe_rate_limit(self) -> None: ...  # provided by _seeding

    async def find_open_resolving_pr(self, issue_number: int) -> int | None:
        """In-memory mirror of :meth:`PRPort.find_open_resolving_pr` (#10260).

        Unlike the real adapter (which parses ``Fixes #N`` from the PR
        body), the fake's ``FakePR.issue_number`` already encodes the link.
        Draft PRs are excluded, mirroring the real adapter.
        """
        self._maybe_rate_limit()
        for pr in self._prs.values():
            if (
                pr.issue_number == issue_number
                and not pr.merged
                and not pr.closed
                and not pr.draft
            ):
                return pr.number
        return None

    async def find_label_drift(self) -> list[LabelDrift]:
        """In-memory mirror of :meth:`PRPort.find_label_drift` (ADR-0088).

        Walks open, non-merged PRs and pairs each with its linked issue;
        classifies drift kinds the same way ``PRManager.find_label_drift``
        classifies them.
        """
        self._maybe_rate_limit()
        pre_pr_labels = {"hydraflow-ready", "hydraflow-plan", "hydraflow-find"}
        post_pr_labels = {"hydraflow-fixed", "hydraflow-hitl"}
        out: list[LabelDrift] = []
        for pr in self._prs.values():
            if pr.merged:
                continue
            issue = self._issues.get(pr.issue_number)
            if issue is None:
                continue
            # Mirror PRManager.find_label_drift: the in-progress claim marker
            # (#10168) is not a pipeline stage, so exclude it from the stage
            # pick — a ready+in-progress issue must read as ``hydraflow-ready``.
            pr_pipeline = next(
                (
                    lbl
                    for lbl in pr.labels
                    if lbl.startswith("hydraflow-") and lbl != "hydraflow-in-progress"
                ),
                "",
            )
            issue_pipeline = next(
                (
                    lbl
                    for lbl in issue.labels
                    if lbl.startswith("hydraflow-") and lbl != "hydraflow-in-progress"
                ),
                "",
            )
            commits = pr.commits

            # More specific — checked first (#10260): a resolved-but-stale
            # escalation label outranks the pipeline-stage drift kinds below.
            # Requires BOTH labels — see the matching comment in
            # PRManager.find_label_drift for why bare `hitl-escalation`
            # (filed by loops other than diagnostic_loop, with no pipeline
            # label backing it) must not be cleared this way. Draft PRs are
            # excluded — mirrors find_open_resolving_pr's draft check.
            escalations = set(issue.labels) & {"hitl-escalation", "diagnose-failed"}
            kind: str | None = None
            issue_label = issue_pipeline
            if (
                {"hitl-escalation", "diagnose-failed"} <= set(issue.labels)
                and not pr.draft
                and pr.checks
                and all(
                    state.upper() in {"SUCCESS", "NEUTRAL", "SKIPPED"}
                    for _name, state in pr.checks
                )
            ):
                kind = "escalated_with_resolving_pr"
                issue_label = ",".join(sorted(escalations))

            if kind is None:
                if (
                    issue_pipeline in pre_pr_labels
                    and pr_pipeline == "hydraflow-review"
                    and commits > 0
                ):
                    kind = "pr_ahead_of_issue"
                elif pr_pipeline in pre_pr_labels and commits > 0:
                    kind = "pr_at_pre_pr_stage"
                elif pr_pipeline in post_pr_labels and issue_pipeline in pre_pr_labels:
                    kind = "pr_ahead_of_issue"

            if kind is None:
                continue
            out.append(
                LabelDrift(
                    issue=pr.issue_number,
                    pr=pr.number,
                    pr_commits=commits,
                    issue_label=issue_label,
                    pr_label=pr_pipeline,
                    kind=kind,  # type: ignore[arg-type]
                    detected_at=datetime.now(UTC),
                )
            )
        return out

    async def find_closed_stage_labeled_issues(
        self,
    ) -> list[ClosedStageLabelDrift]:
        """In-memory mirror of :meth:`PRPort.find_closed_stage_labeled_issues`.

        Reports CLOSED issues that still carry an active ``hydraflow-*``
        pipeline-stage label (#10394). Terminal markers (``hydraflow-fixed`` /
        ``hydraflow-verify``) are excluded — they record shipped/verified
        state, mirroring ``HydraFlowConfig.dispatchable_stage_labels``.
        """
        self._maybe_rate_limit()
        out: list[ClosedStageLabelDrift] = []
        for issue in self._issues.values():
            if issue.state != "closed":
                continue
            stale = sorted(
                lbl for lbl in issue.labels if lbl in _DISPATCHABLE_STAGE_LABELS
            )
            if stale:
                out.append(
                    ClosedStageLabelDrift(issue=issue.number, stale_labels=stale)
                )
        return out
