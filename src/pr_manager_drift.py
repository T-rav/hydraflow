"""Label-drift and stale-state audit sweeps of :class:`pr_manager.PRManager`.

Extracted VERBATIM from ``pr_manager.py`` (god-class decomposition, Refs
#11547) as a mixin, same shape as ``pr_manager_promotion.py``. ``PRManager``
inherits :class:`PRManagerDriftMixin`, so ``PRManager().find_label_drift``
resolves unchanged.

One cohesive concern: read-only reconciliation sweeps that compare what the
label state machine (ADR-0002) *claims* against what GitHub actually shows —
issues stuck on a stage label their PR has moved past, closed issues still
carrying a stage label, and the open PR that resolves a given issue. These
join issue state to PR state, so they sit beside neither surface alone.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from false_close import CLOSE_KEYWORD_RE, closing_issue_refs
from models import ClosedStageLabelDrift, LabelDrift

if TYPE_CHECKING:
    from typing import Any

    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.pr_manager")


class PRManagerDriftMixin:
    """Label-drift audit sweeps mixed into :class:`pr_manager.PRManager`."""

    # ------------------------------------------------------------------
    # Collaborator seams — attributes and methods provided by PRManager or a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would take precedence over the real
    # implementation whenever the declaring mixin precedes the implementing
    # one in PRManager's MRO.
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _repo: str
    _PASSING_STATES: frozenset[str]

    if TYPE_CHECKING:

        def _assert_repo(self) -> None: ...  # provided by PRManager

        async def _gh_json_query(
            self, *args: Any, **kwargs: Any
        ) -> Any: ...  # provided by PRManager

        async def get_pr_checks(
            self, pr_number: int
        ) -> list[dict[str, str]]: ...  # provided by PRManagerCIMixin

        async def _pr_commit_count(
            self, pr_number: int
        ) -> int: ...  # provided by PRManagerPRQueriesMixin

    async def find_label_drift(self) -> list[LabelDrift]:
        """Scan open PRs for cross-entity label drift vs their linked issues.

        Returns a list of :class:`LabelDrift` records, one per drifted pair.
        See ADR-0088 for the drift kinds and reconciliation policy.

        Each tick: fetch open PRs (any state), parse ``Fixes #N`` from the
        body, fetch the linked issue's labels, then classify the pair.
        """
        raw = await self._gh_json_query(
            "gh",
            "pr",
            "list",
            "--repo",
            self._repo,
            "--state",
            "open",
            "--limit",
            "200",
            "--json",
            "number,labels,body,isDraft",
            dry_run_return=[],
            error_log="find_label_drift: pr list failed",
        )
        if not isinstance(raw, list):
            return []

        out: list[LabelDrift] = []
        pre_pr_labels = {"hydraflow-ready", "hydraflow-plan", "hydraflow-find"}
        post_pr_labels = {"hydraflow-fixed", "hydraflow-hitl"}

        for pr in raw:
            if not isinstance(pr, dict):
                continue
            try:
                pr_n = int(pr.get("number", 0))
            except (TypeError, ValueError):
                continue
            if pr_n <= 0:
                continue
            pr_labels = {
                lbl.get("name", "")
                for lbl in (pr.get("labels") or [])
                if isinstance(lbl, dict)
            }
            # The in-progress claim marker (#10168) is not a pipeline stage —
            # exclude it so a ready+in-progress issue reads as ``hydraflow-ready``
            # rather than being mistaken for a stage and mis-classified as drift.
            claim_labels = set(self._config.in_progress_label)
            pr_pipeline = next(
                (
                    lbl
                    for lbl in pr_labels
                    if lbl.startswith("hydraflow-") and lbl not in claim_labels
                ),
                "",
            )
            body = pr.get("body") or ""
            matched_issue_ns = list(
                dict.fromkeys(int(m.group(1)) for m in CLOSE_KEYWORD_RE.finditer(body))
            )
            if not matched_issue_ns:
                continue
            issue_n = matched_issue_ns[0]

            # Commit count is fetched per-PR (only for Fixes-matched PRs, which
            # already trigger an issue fetch below) — requesting `commits` in the
            # bulk `pr list` expands each commit's authors connection and blows
            # past GitHub's GraphQL 500k-node ceiling at --limit 200.
            commits = await self._pr_commit_count(pr_n)

            issue_labels_raw = await self._gh_json_query(
                "gh",
                "issue",
                "view",
                str(issue_n),
                "--repo",
                self._repo,
                "--json",
                "labels",
                dry_run_return={"labels": []},
                error_log=f"find_label_drift: issue {issue_n} fetch failed",
            )
            if not isinstance(issue_labels_raw, dict):
                continue
            issue_labels = {
                lbl.get("name", "")
                for lbl in (issue_labels_raw.get("labels") or [])
                if isinstance(lbl, dict)
            }
            issue_pipeline = next(
                (
                    lbl
                    for lbl in issue_labels
                    if lbl.startswith("hydraflow-") and lbl not in claim_labels
                ),
                "",
            )

            # More specific — checked first (#10260): a resolved-but-stale
            # escalation label outranks the pipeline-stage drift kinds below.
            # Requires BOTH labels, not just `hitl-escalation`: diagnostic_loop
            # is the only lineage that pairs them, and it always swaps the
            # issue to `hydraflow-hitl` first — so clearing still leaves a
            # durable queue label behind. Other loops (corpus_learning_loop,
            # trust_fleet_sanity_loop, wiki_rot_detector_loop, etc.) file bare
            # `hitl-escalation` + their own `-stuck` label with NO pipeline
            # label; clearing `hitl-escalation` for those would orphan the
            # issue with no re-escalation path, since those loops don't
            # re-file until the operator closes it. Draft PRs are excluded —
            # a not-ready-for-review PR isn't a reliable resolved signal even
            # with green CI (mirrors find_open_resolving_pr's draft check).
            # A body can link more than one issue (e.g. an epic PR) — the
            # escalated issue may not be the first Fixes/Closes/Resolves
            # match, so every matched issue is a candidate, not just the
            # primary one already fetched above (#10260 review; mirrors
            # find_open_resolving_pr's finditer scan).
            escalation_issue_n = issue_n
            escalation_labels = issue_labels
            if not ({"hitl-escalation", "diagnose-failed"} <= escalation_labels):
                for candidate_n in matched_issue_ns[1:]:
                    candidate_raw = await self._gh_json_query(
                        "gh",
                        "issue",
                        "view",
                        str(candidate_n),
                        "--repo",
                        self._repo,
                        "--json",
                        "labels",
                        dry_run_return={"labels": []},
                        error_log=(
                            f"find_label_drift: issue {candidate_n} fetch failed"
                        ),
                    )
                    if not isinstance(candidate_raw, dict):
                        continue
                    candidate_labels = {
                        lbl.get("name", "")
                        for lbl in (candidate_raw.get("labels") or [])
                        if isinstance(lbl, dict)
                    }
                    if {"hitl-escalation", "diagnose-failed"} <= candidate_labels:
                        escalation_issue_n = candidate_n
                        escalation_labels = candidate_labels
                        break

            escalations = escalation_labels & {"hitl-escalation", "diagnose-failed"}
            kind: str | None = None
            issue_label = issue_pipeline
            if {
                "hitl-escalation",
                "diagnose-failed",
            } <= escalation_labels and not pr.get("isDraft"):
                checks = await self.get_pr_checks(pr_n)
                if checks and all(
                    c.get("state", "").upper() in self._PASSING_STATES for c in checks
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
                    issue=(
                        escalation_issue_n
                        if kind == "escalated_with_resolving_pr"
                        else issue_n
                    ),
                    pr=pr_n,
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
        """Return CLOSED issues that still carry an active pipeline-stage label.

        Belt-and-suspenders for #10394: a GitHub-native ``Closes #N``
        auto-close (or any close path that bypassed
        :meth:`close_issue`'s label strip) can leave a closed issue tagged
        ``hydraflow-ready`` etc., which a label-scan dispatcher would
        re-queue as duplicate work. The ``LabelDriftWatcherLoop`` (ADR-0088)
        strips them. One search request keyed on the active stage labels
        (comma-joined = GitHub label OR), scoped to ``is:closed``.
        """
        self._assert_repo()
        stage_labels = self._config.dispatchable_stage_labels
        if not stage_labels:
            return []
        search = "is:closed label:" + ",".join(stage_labels)
        raw = await self._gh_json_query(
            "gh",
            "issue",
            "list",
            "--repo",
            self._repo,
            "--state",
            "closed",
            "--search",
            search,
            "--limit",
            "200",
            "--json",
            "number,labels",
            dry_run_return=[],
            error_log="find_closed_stage_labeled_issues: issue list failed",
        )
        if not isinstance(raw, list):
            return []
        stage_set = set(stage_labels)
        out: list[ClosedStageLabelDrift] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                issue_n = int(item.get("number", 0))
            except (TypeError, ValueError):
                continue
            if issue_n <= 0:
                continue
            labels = {
                lbl.get("name", "")
                for lbl in (item.get("labels") or [])
                if isinstance(lbl, dict)
            }
            stale = sorted(labels & stage_set)
            if stale:
                out.append(ClosedStageLabelDrift(issue=issue_n, stale_labels=stale))
        return out

    async def find_open_resolving_pr(self, issue_number: int) -> int | None:
        """Return the number of an OPEN PR that resolves *issue_number*.

        Reuses the ``find_label_drift`` Fixes-regex scan, keyed by issue
        instead of by PR (#10260). Draft PRs are excluded — a PR the author
        marked not-ready-for-review is not a reliable signal that the issue
        is actually resolved, even with green CI.
        """
        raw = await self._gh_json_query(
            "gh",
            "pr",
            "list",
            "--repo",
            self._repo,
            "--state",
            "open",
            "--limit",
            "200",
            "--json",
            "number,body,isDraft",
            dry_run_return=[],
            error_log=f"find_open_resolving_pr: pr list failed for issue #{issue_number}",
        )
        if not isinstance(raw, list):
            return None

        for pr in raw:
            if not isinstance(pr, dict):
                continue
            if pr.get("isDraft"):
                continue
            body = pr.get("body") or ""
            # A body can carry more than one closing link (e.g. an epic PR
            # resolving several issues) — ``closing_issue_refs`` collects every
            # match, not just the first, so this issue's link isn't missed when
            # it isn't the leftmost one.
            if issue_number not in closing_issue_refs(body):
                continue
            try:
                pr_n = int(pr.get("number", 0))
            except (TypeError, ValueError):
                continue
            if pr_n > 0:
                return pr_n
        return None
