"""The per-PR review flow (P3b of #10682, ADR-0111) of ``ReviewPhase``.

Extracted VERBATIM from ``_phase.py`` (god-class decomposition, Refs #11547)
as a mixin — the same shape ``_visual_gate.py`` took in the #10840 pass.
``ReviewPhase`` inherits it, so every method here still resolves as an
attribute of ``ReviewPhase`` and instance/class-level patching in tests still
lands.

One concern: the explicit ``src.flows.Flow`` that drives a single PR review —
its initial state, its node/edge wiring, each node body, and the three
``_run_*`` step helpers the nodes delegate to. Every node reads and writes the
same ``FlowState``; the actuators they call live in the sibling mixins.

The flow's node roles and routing contract are documented in
``_review_flow_notes`` below, moved here with the code it describes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from flows import Edge, Flow, FlowState, KillSwitch, Node, NodeHook
from models import HitlEscalation, ReviewResult, ReviewVerdict

from ._common import PreReviewContext, ReviewGuardContext

if TYPE_CHECKING:
    from pathlib import Path

    from config import HydraFlowConfig
    from models import (
        BaselineApprovalResult,
        CodeScanningAlert,
        PRInfo,
        Task,
        VisualValidationDecision,
        VisualValidationReport,
    )
    from ports import PRPort
    from review_advisor import ReviewPlan

logger = logging.getLogger("hydraflow.review_phase")

# ---------------------------------------------------------------------------
# Review flow (P3b of #10682, ADR-0111) — edge guards
# ---------------------------------------------------------------------------
#
# The per-PR review pipeline runs as an explicit ``src.flows.Flow``:
#
#     guards -> pre-review -> pre-flight -> review -> post-review -> gate
#         guards       --(issue-missing / merge-conflict)--> done
#         pre-review   --(baseline-block / early ReviewResult)--> done
#         gate         --(APPROVE handled by the convergence gate)--> cleanup
#         gate         --> route -> cleanup -> done
#
# Node roles map 1:1 to the pre-refactor straight-line ``_review_one_inner``
# body plus the ``_run_post_review_actions`` tail:
#
# * ``guards``       — publish "start", reset the per-cycle pre-flight plan, run
#   ``_run_initial_guards`` (issue lookup + worktree/merge-with-main). A returned
#   ``ReviewResult`` (issue-not-found, merge-conflict) sets ``result`` + ``_stop``
#   and routes straight to ``done`` (mirrors the old early ``return``s).
# * ``pre-review``   — ``_run_pre_review_checks`` (baseline policy, visual
#   decision, code-scanning fetch, delta verify). A baseline block returns a
#   ``ReviewResult`` → ``_stop`` → ``done``.
# * ``pre-flight``   — ``_run_pre_flight_advisor`` (the PreFlightAdvisor plan).
# * ``review``       — the adversarial-review node: the sole primary reviewer
#   actuator (``_run_and_post_review`` → ``ReviewRunner.review`` + the
#   ``_check_adversarial_threshold`` council). Records ``result``.
# * ``post-review``  — ultra-tier fold + the REQUEST_CHANGES/COMMENT re-review
#   fix loop + visual validation + outcome recording + the product-track
#   pre-merge spec check. The head of the former ``_run_post_review_actions``.
# * ``gate``         — the convergence gate on the APPROVE path
#   (``_handle_approved_review_gated`` → ``_convergence_decision``,
#   ADR-0094–0098). ADVANCE → merge; LOOP_BACK → re-queue to ``ready``;
#   ESCALATE → HITL. Sets ``skip_worktree_cleanup`` and marks the approve path
#   handled so ``route`` is skipped — exactly as the old ``return`` after the
#   approve branch did.
# * ``route``        — the REQUEST_CHANGES/COMMENT reject route
#   (``_handle_rejected_review`` → the same convergence gate at the reject
#   boundary). Only reached when the approve path did NOT fire.
# * ``cleanup``      — ``_cleanup_worktree`` (destroy vs preserve per the gate/
#   route ``skip_worktree_cleanup`` flag).
# * ``done``         — terminal sink carrying the final ``result``.
#
# Every fail-closed early exit sets ``state['_stop']`` (routed to ``done`` by the
# ``_flow_stopped`` guard). The primary reviewer call lives inside ``review``;
# the convergence gate (which itself invokes the post-verify lens judge) lives
# in ``gate`` / ``route``. Routing between nodes is deterministic. ``_review_one``
# keeps its scaffolding (semaphore, span, stop-event, ``run_with_fatal_guard``,
# active-issue bookkeeping); ``_review_one_inner`` keeps the reviewer tracing
# lifecycle and now builds + runs the flow. ``_run_post_review_actions`` re-enters
# the same flow at ``post-review`` via ``Flow.resume`` (mirroring P2's
# ``_handle_implementation_result``) so the post-review tail has a single source
# of truth and cannot drift between the two entry points.
#
# PARITY NOTE (per #10682 requirement 4): ``_run_post_review_actions`` remains a
# public seam with an unchanged signature + return contract because five unit
# tests drive it directly and pin the full fix-loop → gate → cleanup behaviour.
# The convergence gate is therefore reached AS its own ``gate`` node in the live
# ``_review_one_inner`` walk, but the direct-call contract is preserved by having
# the method resume the flow rather than duplicating the sequence.


def _flow_stopped(state: FlowState) -> bool:
    """Edge guard: a node signalled a fail-closed early exit → route to ``done``."""
    return bool(state.get("_stop"))


def _approve_path_handled(state: FlowState) -> bool:
    """Edge guard: the ``gate`` node handled the APPROVE path → skip ``route``.

    Mirrors the pre-refactor ``return result`` immediately after the APPROVE
    branch of ``_run_post_review_actions``: once the convergence gate ran on an
    approved review the reject route must NOT also run.
    """
    return bool(state.get("_approve_handled"))


class ReviewFlowMixin:
    """The per-PR review flow (P3b of #10682, ADR-0111) of ``ReviewPhase``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``ReviewPhase.__init__`` or by a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would win over the real
    # implementation whenever this mixin precedes the implementing one
    # in ``ReviewPhase``'s MRO.
    # ------------------------------------------------------------------
    _advisor_pre_flight_plan: dict[tuple[str, int], ReviewPlan]
    _config: HydraFlowConfig
    _prs: PRPort

    if TYPE_CHECKING:

        async def _attempt_review_fix(
            self,
            pr: PRInfo,
            task: Task,
            wt_path: Path,
            result: ReviewResult,
            diff: str,
            worker_id: int,
            code_scanning_alerts: list[CodeScanningAlert] | None = None,
            advisor_transcript: str | None = None,
            suggested_fix_direction: str | None = None,
            surface: str = "pr_review",
        ) -> tuple[ReviewResult, str]: ...  # provided by _self_fix

        async def _check_baseline_policy(
            self, pr: PRInfo, task: Task
        ) -> BaselineApprovalResult | None: ...  # provided by _phase

        async def _cleanup_worktree(
            self, pr: PRInfo, result: ReviewResult, skip: bool
        ) -> None: ...  # provided by _phase

        def _compute_visual_validation(
            self, diff: str, task: Task
        ) -> VisualValidationDecision | None: ...  # provided by _visual_gate

        async def _escalate_to_hitl(
            self, esc: HitlEscalation
        ) -> None: ...  # provided by _insights

        async def _fetch_code_scanning_alerts(
            self, pr: PRInfo
        ) -> list[CodeScanningAlert] | None: ...  # provided by _phase

        async def _handle_approved_review_gated(
            self,
            pr: PRInfo,
            task: Task,
            wt_path: Path,
            result: ReviewResult,
            diff: str,
            worker_id: int,
            *,
            surface: str,
            code_scanning_alerts: list[CodeScanningAlert] | None,
            visual_decision: VisualValidationDecision | None,
        ) -> bool: ...  # provided by _outcome

        async def _handle_rejected_review(
            self,
            pr: PRInfo,
            task: Task,
            result: ReviewResult,
            worker_id: int,
        ) -> bool: ...  # provided by _outcome

        async def _handle_self_fix_re_review(
            self,
            pr: PRInfo,
            issue: Task,
            wt_path: Path,
            result: ReviewResult,
            diff: str,
            worker_id: int,
            code_scanning_alerts: list[CodeScanningAlert] | None = None,
            surface: str = "pr_review",
        ) -> tuple[ReviewResult, str]: ...  # provided by _self_fix

        async def _handle_visual_failure(
            self,
            pr: PRInfo,
            task: Task,
            result: ReviewResult,
            report: VisualValidationReport,
            worker_id: int,
        ) -> ReviewResult: ...  # provided by _visual_gate

        @staticmethod
        def _is_product_track_pr(task: Task) -> bool: ...  # provided by _phase

        async def _maybe_fold_ultra_review(
            self,
            pr: PRInfo,
            result: ReviewResult,
            diff: str,
        ) -> ReviewResult: ...  # provided by _ultra

        async def _prepare_review_worktree(
            self, pr: PRInfo, task: Task, idx: int
        ) -> Path | None: ...  # provided by _phase

        async def _publish_review_status(
            self, pr: PRInfo, worker_id: int, status: str
        ) -> None: ...  # provided by _insights

        async def _record_review_outcome(
            self, pr: PRInfo, result: ReviewResult
        ) -> None: ...  # provided by _phase

        async def _run_and_post_review(
            self,
            pr: PRInfo,
            issue: Task,
            wt_path: Path,
            diff: str,
            worker_id: int,
            code_scanning_alerts: list[CodeScanningAlert] | None = None,
            pre_flight_plan: ReviewPlan | None = None,
            surface: str = "pr_review",
        ) -> ReviewResult: ...  # provided by _phase

        async def _run_delta_verification(
            self, pr: PRInfo, diff: str
        ) -> str: ...  # provided by _self_fix

        async def _run_pre_flight_advisor(
            self,
            pr: PRInfo,
            task: Task,
            diff: str,
            surface: str = "pr_review",
        ) -> None: ...  # provided by _advisors

        async def _run_pre_merge_spec_check(
            self, task: Task, diff: str, pr_number: int | None = None
        ) -> bool: ...  # provided by _advisors

        async def _run_visual_validation(
            self, pr: PRInfo, wt_path: Path, worker_id: int
        ) -> VisualValidationReport | None: ...  # provided by _visual_gate

    @staticmethod
    def _initial_review_state(
        idx: int,
        pr: PRInfo,
        issue_map: dict[int, Task],
        surface: str,
    ) -> FlowState:
        """Seed the review flow's shared working state for one PR."""
        return {
            "idx": idx,
            "pr": pr,
            "issue_map": issue_map,
            "surface": surface,
        }

    def _build_review_flow(
        self,
        *,
        checkpoint: NodeHook | None = None,
        kill_switch: KillSwitch | None = None,
    ) -> Flow:
        """Build the per-PR review DAG (P3b of #10682, ADR-0111).

        See the module-level diagram for node roles. ``checkpoint`` /
        ``kill_switch`` stay injected per ADR-0111 so the primitive's
        persistence + halt seams are wired-through and testable. The production
        entry runs without a checkpoint: a single review tick needs no resume,
        and writing one would be a new on-disk side effect this parity-gated,
        no-flag refactor must not introduce. Per-node ``on_node`` event wiring
        is deferred to a later phase per ADR-0111.
        """
        return Flow(
            nodes=[
                Node("guards", self._flow_guards, kind="gate"),
                Node("pre-review", self._flow_pre_review, kind="gate"),
                Node("pre-flight", self._flow_pre_flight),
                Node("review", self._flow_review),
                Node("post-review", self._flow_post_review),
                Node("gate", self._flow_gate, kind="gate"),
                Node("route", self._flow_route, kind="gate"),
                Node("cleanup", self._flow_cleanup),
                Node("done", self._flow_done),
            ],
            edges=[
                # First-match-wins: a stopped node skips straight to the sink.
                Edge("guards", "done", when=_flow_stopped),
                Edge("guards", "pre-review"),
                Edge("pre-review", "done", when=_flow_stopped),
                Edge("pre-review", "pre-flight"),
                Edge("pre-flight", "review"),
                Edge("review", "post-review"),
                Edge("post-review", "gate"),
                # The convergence gate handled the APPROVE path → skip the
                # reject route (mirrors the pre-refactor ``return`` after the
                # approve branch).
                Edge("gate", "cleanup", when=_approve_path_handled),
                Edge("gate", "route"),
                Edge("route", "cleanup"),
                Edge("cleanup", "done"),
            ],
            entry="guards",
            checkpoint=checkpoint,
            kill_switch=kill_switch,
        )

    async def _flow_guards(self, state: FlowState) -> FlowState:
        """Publish "start", reset the pre-flight plan, run the initial guards.

        Reproduces the head of the pre-refactor ``_review_one_inner`` body: a
        returned ``ReviewResult`` (issue-not-found, merge-conflict) is a
        fail-closed early exit — it sets ``result`` + ``_stop`` and routes
        straight to ``done`` (the old early ``return``, which ran no
        post-review handling and no worktree cleanup).
        """
        pr = state["pr"]
        idx = state["idx"]
        issue_map = state["issue_map"]
        surface = state["surface"]

        await self._publish_review_status(pr, idx, "start")

        # Reset per-PR pre-flight plan on every review entry. The plan is
        # scoped to a single review cycle and must not leak across reviews
        # of the same PR — reusing a stale plan from the prior cycle would
        # feed an out-of-date rubric to both the executor's prompt and the
        # post-verify advisor.
        self._advisor_pre_flight_plan.pop((surface, pr.number), None)

        guards = await self._run_initial_guards(idx, pr, issue_map)
        if isinstance(guards, ReviewResult):
            state["result"] = guards
            state["_stop"] = True
            return state
        state["task"] = guards.task
        state["workspace_path"] = guards.workspace_path
        return state

    async def _flow_pre_review(self, state: FlowState) -> FlowState:
        """Baseline / visual / delta pre-review checks.

        A baseline block returns a ``ReviewResult`` — a fail-closed early exit
        (``_stop`` → ``done``) exactly as the pre-refactor early ``return`` did.
        """
        pr = state["pr"]
        task = state["task"]
        pre_review = await self._run_pre_review_checks(pr, task)
        if isinstance(pre_review, ReviewResult):
            state["result"] = pre_review
            state["_stop"] = True
            return state
        state["pre_review"] = pre_review
        return state

    async def _flow_pre_flight(self, state: FlowState) -> FlowState:
        """PreFlightAdvisor plan node (no verdict — populates the pre-flight plan)."""
        pr = state["pr"]
        task = state["task"]
        pre_review = state["pre_review"]
        surface = state["surface"]
        await self._run_pre_flight_advisor(pr, task, pre_review.diff, surface=surface)
        return state

    async def _flow_review(self, state: FlowState) -> FlowState:
        """The adversarial-review node: the sole primary reviewer actuator.

        Delegates to ``_run_and_post_review`` (``ReviewRunner.review`` + the
        ``_check_adversarial_threshold`` council). Records ``result``.
        """
        pr = state["pr"]
        task = state["task"]
        wt_path = state["workspace_path"]
        pre_review = state["pre_review"]
        idx = state["idx"]
        surface = state["surface"]
        result = await self._run_and_post_review(
            pr,
            task,
            wt_path,
            pre_review.diff,
            idx,
            code_scanning_alerts=pre_review.code_scanning_alerts,
            pre_flight_plan=self._advisor_pre_flight_plan.get((surface, pr.number)),
            surface=surface,
        )
        state["result"] = result
        return state

    async def _flow_post_review(self, state: FlowState) -> FlowState:
        """Ultra fold + fix loop + visual + record + product-track spec check.

        The head of the former ``_run_post_review_actions`` (steps up to — but
        not including — the APPROVE/reject routing, which are the ``gate`` /
        ``route`` nodes). Copied verbatim from the pre-refactor body to preserve
        the exact call order; the (possibly upgraded) ``result`` and (possibly
        refreshed) ``diff`` are threaded forward in ``state``.
        """
        pr = state["pr"]
        task = state["task"]
        wt_path = state["workspace_path"]
        result = state["result"]
        pre_review = state["pre_review"]
        worker_id = state["idx"]

        diff = pre_review.diff
        code_scanning_alerts = pre_review.code_scanning_alerts

        # Opt-in ultra deep-review tier (#10555). No-op when the dial is off;
        # when it fires, material findings flip an APPROVE verdict here so the
        # existing REQUEST_CHANGES fix hand-back below runs.
        result = await self._maybe_fold_ultra_review(pr, result, diff)

        if result.verdict in (
            ReviewVerdict.REQUEST_CHANGES,
            ReviewVerdict.COMMENT,
        ):
            if result.fixes_made:
                result, diff = await self._handle_self_fix_re_review(
                    pr,
                    task,
                    wt_path,
                    result,
                    diff,
                    worker_id,
                    code_scanning_alerts=code_scanning_alerts,
                )
            else:
                result, diff = await self._attempt_review_fix(
                    pr,
                    task,
                    wt_path,
                    result,
                    diff,
                    worker_id,
                    code_scanning_alerts=code_scanning_alerts,
                )

        visual_report = await self._run_visual_validation(pr, wt_path, worker_id)
        if visual_report and visual_report.has_failures:
            result = await self._handle_visual_failure(
                pr,
                task,
                result,
                visual_report,
                worker_id,
            )

        await self._record_review_outcome(pr, result)

        # Pre-merge spec check for product-track issues
        if (
            result.verdict == ReviewVerdict.APPROVE
            and pr.number > 0
            and self._is_product_track_pr(task)
        ):
            spec_ok = await self._run_pre_merge_spec_check(
                task, diff, pr_number=pr.number
            )
            if not spec_ok:
                result = result.model_copy(
                    update={
                        "verdict": ReviewVerdict.REQUEST_CHANGES,
                        "summary": (result.summary or "")
                        + "\n\nSpec-match check failed: implementation does not fully "
                        "match the product direction from Shape. See spec-match "
                        "comment on the issue.",
                    }
                )

        state["result"] = result
        state["diff"] = diff
        return state

    async def _flow_gate(self, state: FlowState) -> FlowState:
        """Convergence gate on the APPROVE path (ADR-0094–0098).

        Reproduces the APPROVE branch of ``_run_post_review_actions``: when the
        verdict is APPROVE and the PR is real, ``_handle_approved_review_gated``
        routes through ``_convergence_decision`` (ADVANCE → merge / LOOP_BACK →
        re-queue to ``ready`` / ESCALATE → HITL) and returns the
        ``skip_worktree_cleanup`` flag. Marking the approve path handled makes
        the outgoing edge skip ``route`` — the flow analogue of the pre-refactor
        ``return result`` that fired immediately after this branch.
        """
        pr = state["pr"]
        task = state["task"]
        wt_path = state["workspace_path"]
        result = state["result"]
        diff = state["diff"]
        worker_id = state["idx"]
        surface = state["surface"]
        pre_review = state["pre_review"]

        if result.verdict == ReviewVerdict.APPROVE and pr.number > 0:
            state["skip_worktree_cleanup"] = await self._handle_approved_review_gated(
                pr,
                task,
                wt_path,
                result,
                diff,
                worker_id,
                surface=surface,
                code_scanning_alerts=pre_review.code_scanning_alerts,
                visual_decision=pre_review.visual_decision,
            )
            state["_approve_handled"] = True
        return state

    async def _flow_route(self, state: FlowState) -> FlowState:
        """Reject route for REQUEST_CHANGES / COMMENT verdicts.

        Reproduces the reject branch of ``_run_post_review_actions``: only
        reached when the ``gate`` node did NOT handle the APPROVE path.
        ``skip_worktree_cleanup`` starts False (matching the pre-refactor
        initializer) and becomes the ``_handle_rejected_review`` result only on
        a REQUEST_CHANGES / COMMENT verdict.
        """
        pr = state["pr"]
        task = state["task"]
        result = state["result"]
        worker_id = state["idx"]

        skip = False
        if result.verdict in (
            ReviewVerdict.REQUEST_CHANGES,
            ReviewVerdict.COMMENT,
        ):
            skip = await self._handle_rejected_review(
                pr,
                task,
                result,
                worker_id,
            )
        state["skip_worktree_cleanup"] = skip
        return state

    async def _flow_cleanup(self, state: FlowState) -> FlowState:
        """Destroy or preserve the worktree per the gate/route skip flag."""
        pr = state["pr"]
        result = state["result"]
        await self._cleanup_worktree(
            pr, result, bool(state.get("skip_worktree_cleanup"))
        )
        return state

    @staticmethod
    async def _flow_done(state: FlowState) -> FlowState:
        """Terminal sink for the review flow (#10682).

        A no-op join point so every path — the full walk and each fail-closed
        early exit — ends at one observable terminal carrying the final
        ``result``.
        """
        return state

    async def _run_initial_guards(
        self,
        idx: int,
        pr: PRInfo,
        issue_map: dict[int, Task],
    ) -> ReviewResult | ReviewGuardContext:
        """Handle prerequisite guards before running a review."""
        task = issue_map.get(pr.issue_number)
        if task is None:
            return ReviewResult(
                pr_number=pr.number,
                issue_number=pr.issue_number,
                summary="Issue not found",
            )

        wt_path = await self._prepare_review_worktree(pr, task, idx)
        if wt_path is None:
            return ReviewResult(
                pr_number=pr.number,
                issue_number=pr.issue_number,
                summary="Merge conflicts with main — escalated to HITL",
            )

        return ReviewGuardContext(task=task, workspace_path=wt_path)

    async def _run_pre_review_checks(
        self,
        pr: PRInfo,
        task: Task,
    ) -> ReviewResult | PreReviewContext:
        """Run baseline, visual, and delta checks before invoking reviewer."""
        diff = await self._prs.get_pr_diff(pr.number)

        baseline_result = await self._check_baseline_policy(pr, task)
        if (
            baseline_result
            and baseline_result.requires_approval
            and not baseline_result.approved
        ):
            await self._escalate_to_hitl(
                HitlEscalation(
                    issue_number=pr.issue_number,
                    pr_number=pr.number,
                    cause="Baseline changes require approval",
                    origin_label=self._config.review_label[0],
                    comment=(
                        "## Baseline Policy Violation\n\n"
                        "This PR modifies visual baseline files that require "
                        "explicit approval from a designated owner before merging.\n\n"
                        "**Changed baseline files:**\n"
                        + "\n".join(f"- `{f}`" for f in baseline_result.changed_files)
                        + "\n\nPlease request a review from an authorized baseline approver."
                    ),
                    event_cause="baseline_approval_required",
                    task=task,
                )
            )
            return ReviewResult(
                pr_number=pr.number,
                issue_number=pr.issue_number,
                summary="Baseline changes require approval — escalated to HITL",
            )

        visual_decision = self._compute_visual_validation(diff, task)
        if visual_decision is not None and pr.number > 0:
            from visual_validation import (  # noqa: PLC0415
                format_visual_validation_comment,
            )

            await self._prs.post_pr_comment(
                pr.number,
                format_visual_validation_comment(visual_decision),
            )

        code_scanning_alerts = await self._fetch_code_scanning_alerts(pr)
        await self._run_delta_verification(pr, diff)

        return PreReviewContext(
            diff=diff,
            visual_decision=visual_decision,
            code_scanning_alerts=code_scanning_alerts,
        )

    async def _run_post_review_actions(
        self,
        pr: PRInfo,
        task: Task,
        wt_path: Path,
        result: ReviewResult,
        pre_review: PreReviewContext,
        worker_id: int,
        surface: str = "pr_review",
    ) -> ReviewResult:
        """Handle re-review, visual validation, verdict flow, and cleanup.

        ``surface`` is forwarded to the convergence gate's lens judge so the
        post-verify advisor uses the correct surface config (T24.7).
        Defaults to ``"pr_review"`` for back-compat.

        The post-review tail of the review flow (P3b of #10682): the same
        ``post-review -> gate -> (route ->) cleanup`` graph ``_review_one_inner``
        runs, re-entered at the ``post-review`` node with the built ``result``
        pre-seeded (``Flow.resume``, mirroring P2's
        ``_handle_implementation_result``). Keeping this as the single source of
        truth — rather than a second inline copy — means the fix-loop / gate /
        route / cleanup branches can never drift between the two entry points.
        Signature and ``ReviewResult`` return contract are unchanged.
        """
        flow = self._build_review_flow()
        state = self._initial_review_state(
            worker_id, pr, {pr.issue_number: task}, surface
        )
        state["task"] = task
        state["workspace_path"] = wt_path
        state["result"] = result
        state["pre_review"] = pre_review
        outcome = await flow.resume(state, "post-review")
        return outcome.state["result"]
