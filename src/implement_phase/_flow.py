"""The per-issue implement flow (P2 of #10682, ADR-0111) of ``ImplementPhase``.

Extracted VERBATIM from ``src/implement_phase.py`` (god-class
decomposition, Refs #11547) as a mixin — the shape ``review_phase/`` already
uses. ``ImplementPhase`` inherits it, so every method here still resolves as
an attribute of ``ImplementPhase`` and instance/class-level patching in tests
still lands.

One concern: the explicit ``src.flows.Flow`` that drives a single implement
attempt — its seed state, its node/edge wiring, and every node body. The
graph's routing contract and the module-level edge guards it reads live in
``_common.py`` next to the diagram that documents them.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from flows import Edge, Flow, Node
from implement_failure_class import classify_implement_failure
from models import WorkerResult

from ._common import (
    _flow_stopped,
    _open_pr_terminal,
    _route_is_failure_screen,
    _route_is_zero_commit,
)

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from flows import FlowState, KillSwitch, NodeHook
    from models import Task
    from ports import IssueStorePort, PRPort
    from run_recorder import RunRecorder
    from state import StateTracker
    from task_source import TaskTransitioner

logger = logging.getLogger("hydraflow.implement_phase")


class ImplementFlowMixin:
    """The per-issue implement flow (ADR-0111) of ``ImplementPhase``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``ImplementPhase.__init__`` or by
    # a sibling mixin. The method declarations are TYPE_CHECKING-only
    # on purpose: a runtime ``...`` body would win over the
    # real implementation whenever this mixin precedes the
    # implementing one in ``ImplementPhase``'s MRO.
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _prs: PRPort
    _run_recorder: RunRecorder | None
    _state: StateTracker
    _store: IssueStorePort
    _transitioner: TaskTransitioner

    if TYPE_CHECKING:

        async def _abandon_resolved_issue(
            self, issue: Task, branch: str, *, at: str
        ) -> WorkerResult: ...  # provided by _abort

        async def _check_attempt_cap(
            self, issue: Task, branch: str
        ) -> WorkerResult | None: ...  # provided by _abort

        async def _escalate_no_progress(
            self, issue: Task, branch: str
        ) -> WorkerResult: ...  # provided by _abort

        async def _escalate_zero_commit(
            self, issue: Task, result: WorkerResult
        ) -> None: ...  # provided by _abort

        async def _flag_requirements_gaps(
            self, issue: Task, transcript: str
        ) -> None: ...  # provided by _spec_review

        async def _handle_null_delivery(
            self, issue: Task, result: WorkerResult
        ) -> WorkerResult: ...  # provided by _screen

        async def _handle_successful_push(
            self, issue: Task, result: WorkerResult, is_retry: bool
        ) -> WorkerResult | None: ...  # provided by _pr

        async def _handle_zero_commits(
            self, issue: Task, result: WorkerResult
        ) -> WorkerResult: ...  # provided by _screen

        async def _is_null_delivery(
            self, result: WorkerResult
        ) -> bool: ...  # provided by _screen

        @staticmethod
        def _is_zero_commit_failure(
            result: WorkerResult,
        ) -> bool: ...  # provided by _screen

        async def _issue_resolved_elsewhere(
            self, issue_number: int
        ) -> bool: ...  # provided by _abort

        def _log_adversarial_carryover(
            self, issue: Task
        ) -> None: ...  # provided by _build

        def _prepare_adr_plan(self, issue: Task) -> None: ...  # provided by _build

        def _read_plan_for_recording(
            self, issue_number: int
        ) -> str: ...  # provided by _build

        async def _run_implementation(
            self, issue: Task, branch: str, worker_id: int, review_feedback: str
        ) -> WorkerResult: ...  # provided by _build

        async def _run_spec_compliance_review(
            self, issue: Task, result: WorkerResult
        ) -> None: ...  # provided by _spec_review

        def _should_abort_no_progress(
            self, issue: Task
        ) -> bool: ...  # provided by _abort

        def _should_abort_zero_commit(
            self, issue: Task
        ) -> bool: ...  # provided by _abort

    @staticmethod
    def _initial_flow_state(idx: int, issue: Task, branch: str) -> FlowState:
        """Seed the implement flow's shared working state for one attempt."""
        return {"idx": idx, "issue": issue, "branch": branch}

    def _build_implement_flow(
        self,
        *,
        checkpoint: NodeHook | None = None,
        kill_switch: KillSwitch | None = None,
    ) -> Flow:
        """Build the per-issue implement DAG (P2 of #10682, ADR-0111).

        The straight-line ``_worker_inner`` control is re-expressed as an
        explicit flow (see the module-level diagram). Node roles:

        * ``decompose`` — deterministic admission control: read plan-phase
          adversarial carryover, seed an ADR plan, resolve review-feedback /
          retry, take the existing-PR shortcut, enforce the attempt cap. Early
          exits set ``result`` and route to ``done``.
        * ``no-progress-abort`` *(new — the point of P2, #10659/#10616)* —
          before spending another (up to ``agent_timeout``) build, escalate a
          non-converging issue to HITL instead of retry-thrashing to the cap.
        * ``issue-state`` *(new — #11457)* — the last gate before the
          actuator: re-read the issue's state from GitHub and abandon the
          build when the issue was resolved elsewhere between selection and
          branch-cut. Placement after ``no-progress-abort`` is deliberate —
          ``decompose``'s existing-PR shortcut and attempt cap must still run
          first. ``open-pr`` re-checks the same thing before pushing, closing
          the mid-build half of the window.
        * ``build`` — the sole actuator: runs the implementation agent and
          records the run (unchanged from today).
        * ``screen`` — classify the outcome (zero-commit / null-delivery /
          push / no-op) exactly as the pre-refactor ``_handle_implementation_
          result`` head did.
        * ``zero-commit-abort`` *(#11568)* — a zero-commit result at/over
          ``implement_no_progress_abort_attempts`` (default 1: the FIRST one)
          routes to diagnose with the transcript tail and ends the walk,
          instead of spending the W5 reviewer and attempts 2 and 3 on the
          same shape. Below the threshold (or disabled) it falls through to
          ``spec-verify`` — the pre-#11568 retry shape.
        * ``spec-verify`` — reuse ``SpecComplianceReviewer`` via
          ``_run_spec_compliance_review`` (the shared node from the P0.5 map)
          on any failed attempt, plus the screen-specific comment.
        * ``gate`` — the read-only ``retry <= max | route-to-HITL`` disposition
          (enforcement stays in ``decompose``/``no-progress-abort``).
        * ``open-pr`` — push + PR resolution + review handoff for the
          success/retry path.

        ``checkpoint`` / ``kill_switch`` stay injected per ADR-0111 so the
        primitive's persistence + halt seams are wired-through and testable.
        The production entry runs without a checkpoint: a single-attempt build
        needs no resume, and writing one would be a new on-disk side effect
        this parity-gated, no-flag refactor must not introduce. Per-node
        ``on_node`` event wiring is deferred to a later phase per ADR-0111.
        """
        return Flow(
            nodes=[
                Node("decompose", self._flow_decompose, kind="gate"),
                Node(
                    "no-progress-abort",
                    self._flow_no_progress_abort,
                    kind="gate",
                ),
                Node(
                    "issue-state",
                    self._flow_issue_state,
                    kind="gate",
                ),
                Node("build", self._flow_build),
                Node("screen", self._flow_screen, kind="gate"),
                Node(
                    "zero-commit-abort",
                    self._flow_zero_commit_abort,
                    kind="gate",
                ),
                Node("spec-verify", self._flow_spec_verify),
                Node("gate", self._flow_gate, kind="gate"),
                Node("open-pr", self._flow_open_pr),
                Node("done", self._flow_done),
            ],
            edges=[
                # First-match-wins: a stopped node skips straight to the sink.
                Edge("decompose", "done", when=_flow_stopped),
                Edge("decompose", "no-progress-abort"),
                Edge("no-progress-abort", "done", when=_flow_stopped),
                Edge("no-progress-abort", "issue-state"),
                Edge("issue-state", "done", when=_flow_stopped),
                Edge("issue-state", "build"),
                Edge("build", "screen"),
                Edge("screen", "zero-commit-abort", when=_route_is_zero_commit),
                Edge("screen", "spec-verify", when=_route_is_failure_screen),
                Edge("screen", "open-pr"),
                Edge("zero-commit-abort", "done", when=_flow_stopped),
                Edge("zero-commit-abort", "spec-verify"),
                Edge("spec-verify", "gate"),
                Edge("gate", "done"),
                Edge("open-pr", "done", when=_open_pr_terminal),
                Edge("open-pr", "spec-verify"),
            ],
            entry="decompose",
            checkpoint=checkpoint,
            kill_switch=kill_switch,
        )

    async def _flow_decompose(self, state: FlowState) -> FlowState:
        """Admission control: prepare the attempt or short-circuit (#10682).

        Reads plan-phase adversarial carryover, seeds an ADR plan, resolves
        review-feedback / retry into state, takes the existing-PR shortcut, and
        enforces the attempt cap. Any early exit sets ``result`` + ``_stop`` so
        routing skips straight to ``done`` without a build.
        """
        issue = state["issue"]
        branch = state["branch"]

        # Earlier-adversarial pipeline: read carryover concerns surfaced during
        # plan_phase, log them, then proceed. Never blocks — dark-factory.
        self._log_adversarial_carryover(issue)
        self._prepare_adr_plan(issue)

        # If a non-draft PR already exists and this is NOT a review-feedback
        # retry, skip implementation and transition directly to review. This
        # handles issues requeued to hydraflow-ready that already have completed
        # PRs from a prior run.
        review_feedback = self._state.get_review_feedback(issue.id) or ""
        state["review_feedback"] = review_feedback
        state["is_retry"] = bool(review_feedback)
        if not review_feedback:
            existing_pr = await self._prs.find_open_pr_for_branch(
                branch, issue_number=issue.id
            )
            if existing_pr and existing_pr.number > 0 and not existing_pr.draft:
                logger.info(
                    "Issue #%d already has open PR #%d — skipping to review",
                    issue.id,
                    existing_pr.number,
                )
                self._store.enqueue_transition(issue, "review")
                await self._transitioner.transition(
                    issue.id,
                    "review",
                    pr_number=existing_pr.number,
                )
                self._state.increment_session_counter("implemented")
                self._state.mark_issue(issue.id, "success")
                state["result"] = WorkerResult(
                    issue_number=issue.id,
                    branch=branch,
                    success=True,
                    pr_info=existing_pr,
                )
                state["_stop"] = True
                return state

        cap_result = await self._check_attempt_cap(issue, branch)
        if cap_result is not None:
            state["result"] = cap_result
            state["_stop"] = True
        return state

    async def _flow_no_progress_abort(self, state: FlowState) -> FlowState:
        """No-progress early-abort node (P2 of #10682; #10659/#10616).

        The crux of P2: a non-converging issue used to burn up to
        ``max_issue_attempts × agent_timeout`` (≈ 3 × 3600s) of build time
        before the attempt cap escalated it. This node runs BEFORE ``build``
        and, once :meth:`_should_abort_no_progress` confirms the issue is
        thrashing (this attempt is at/over ``implement_no_progress_abort_
        attempts`` and the immediately prior attempt produced no output),
        escalates to HITL immediately — skipping the next full build.

        Review-feedback retries are review-driven, not ready-queue thrash, so
        they are never aborted here.
        """
        issue = state["issue"]
        branch = state["branch"]
        if state.get("review_feedback"):
            return state
        if not self._should_abort_no_progress(issue):
            return state
        state["result"] = await self._escalate_no_progress(issue, branch)
        state["_stop"] = True
        return state

    async def _flow_issue_state(self, state: FlowState) -> FlowState:
        """Re-check the issue's GitHub state immediately before the build (#11457).

        The work-picker validates issue state at selection only; between the
        pick and the branch-cut another PR can close the issue and the local
        cache goes stale — building anyway produced the duplicate PRs behind
        #11443/#11451. GitHub is the source of truth (ADR-0041), so this node
        re-reads it as the LAST gate before the actuator and abandons the
        attempt when the issue was resolved elsewhere. The read fails open:
        only a positive resolved state abandons, never a failed one.
        """
        issue = state["issue"]
        if not await self._issue_resolved_elsewhere(issue.id):
            return state
        state["result"] = await self._abandon_resolved_issue(
            issue, state["branch"], at="branch-cut"
        )
        state["_stop"] = True
        return state

    async def _flow_build(self, state: FlowState) -> FlowState:
        """The actuator node: run the implementation agent and record it.

        This is the only node that spends the (up to ``agent_timeout``) LLM
        build — the actuator boundary. Sets ``state['result']``. Behaviour is
        unchanged from the pre-refactor ``_worker_inner`` body.
        """
        issue = state["issue"]
        branch = state["branch"]
        idx = state["idx"]
        review_feedback = state["review_feedback"]

        # Start recording if a run recorder is available.
        ctx = None
        if self._run_recorder is not None:
            try:
                ctx = self._run_recorder.start(issue.id)
                plan_text = self._read_plan_for_recording(issue.id)
                if plan_text:
                    ctx.save_plan(plan_text)
                ctx.save_config(
                    self._config.model_dump(
                        mode="json",
                        exclude={
                            "gh_token",
                            "whatsapp_token",
                            "whatsapp_phone_id",
                            "whatsapp_recipient",
                            "whatsapp_verify_token",
                        },
                    )
                )
            except (RuntimeError, OSError):
                logger.debug("Run recording setup failed", exc_info=True)
                ctx = None

        # Inject prior reflections into the issue context so the agent benefits
        # from learnings accumulated in previous cycles.
        from reflections import append_reflection, read_reflections  # noqa: PLC0415

        prior_reflections = read_reflections(self._config, issue.id)
        if prior_reflections:
            issue.body = (issue.body or "") + (
                f"\n\n## Prior Reflections\n\n{prior_reflections}"
            )

        result = await self._run_implementation(issue, branch, idx, review_feedback)

        # Failure-class split (#11593 seam 3): classify every failed build at
        # the point the result lands so the System tab shows why attempts die
        # (test_adequacy / timeout / zero_commit / diff_sanity / quality /
        # scope / other) instead of a bare attempt count. Counter updates
        # must never take down the build path.
        failure_class: str | None = None
        if not result.success:
            failure_class = classify_implement_failure(result.error)
            try:
                self._state.increment_implement_failure(failure_class)
            except OSError:
                logger.debug(
                    "implement failure-class counter update failed", exc_info=True
                )

        # Record a reflection for future cycles.
        if result.error:
            append_reflection(
                self._config,
                issue.id,
                "implement",
                f"Attempt {idx} failed: {result.error[:200]}",
            )
        elif result.success:
            append_reflection(
                self._config,
                issue.id,
                "implement",
                f"Attempt {idx} succeeded on branch {branch}.",
            )

        # Finalize the recording.
        if ctx is not None:
            try:
                if result.transcript:
                    for line in result.transcript.splitlines():
                        ctx.append_transcript(line)
                outcome = "success" if result.success else "failed"
                ctx.finalize(
                    outcome,
                    error=result.error,
                    failure_class=failure_class,
                    test_adequacy=(
                        result.test_adequacy.model_dump()
                        if result.test_adequacy is not None
                        else None
                    ),
                )
            except (RuntimeError, OSError):
                logger.debug("Run recording finalize failed", exc_info=True)

        state["result"] = result
        return state

    async def _flow_screen(self, state: FlowState) -> FlowState:
        """Classify the build outcome (#10682 screen node).

        Reproduces the classification precedence of the pre-refactor
        ``_handle_implementation_result`` head — zero-commit first, then
        null-delivery (which mutates ``result`` into a failure), then the
        push/no-op fall-through — writing the branch into ``state['route']``.
        Routing to ``spec-verify`` vs ``open-pr`` is done by the outgoing
        edges.
        """
        result = state["result"]
        is_retry = state["is_retry"]
        if self._is_zero_commit_failure(result):
            state["route"] = "fail_zero_commit"
        elif await self._is_null_delivery(result):
            # Null-delivery guard (issue #9480): a non-empty diff whose every
            # file is a planner diagram / auto-generated artifact is not a real
            # implementation — treat it as a failed attempt.
            result.success = False
            if not result.error:
                result.error = (
                    "Null delivery: implementation produced only planner "
                    "diagrams / auto-generated artifacts, no code or tests"
                )
            state["route"] = "fail_null_delivery"
        elif result.workspace_path and (result.success or is_retry):
            state["route"] = "push"
        else:
            state["route"] = "final_only"
        return state

    async def _flow_zero_commit_abort(self, state: FlowState) -> FlowState:
        """Route a zero-commit result to diagnose instead of attempt N+1 (#11568).

        Measured 2026-08-21: attempts per merged issue doubled (1.2 → 2.2);
        13 of 153 implement results ended "No commits found on branch" and
        each then burned a second and third full build on the same shape. A
        zero-commit attempt is not a partial success to retry blindly. When
        this attempt is at/over ``implement_no_progress_abort_attempts``
        (default 1 — the first one), escalate now through the shared
        diagnose/HITL escalator with the transcript tail, skip the W5 spec
        review (there is no diff to review) and end the walk. Below the
        threshold, or with the abort disabled (0), fall through to
        ``spec-verify`` — the pre-#11568 corrective-retry shape.

        Credit exhaustion never reaches here: ``AgentRunner.run`` re-raises
        ``CreditExhaustedError`` before a ``WorkerResult`` exists, so the
        ADR-0119 pause is untouched.
        """
        issue = state["issue"]
        if not self._should_abort_zero_commit(issue):
            return state
        await self._escalate_zero_commit(issue, state["result"])
        state["disposition"] = "escalate"
        state["_stop"] = True
        return state

    async def _flow_spec_verify(self, state: FlowState) -> FlowState:
        """Handle a failed attempt + reuse ``SpecComplianceReviewer`` (#10682).

        The shared spec-verify node from the P0.5 map. Runs the screen-specific
        failure handler (zero-commit / null-delivery comment + mark-failed) when
        applicable, then dispatches ``_run_spec_compliance_review`` (ADR-0063
        W5) so the next attempt sees concrete gaps. Push-path failures (a failed
        review-feedback retry, a committed-but-failed fresh attempt) reach here
        already marked failed by ``open-pr`` — for those it runs the spec review
        only.
        """
        issue = state["issue"]
        result = state["result"]
        route = state["route"]
        if route == "fail_zero_commit":
            await self._handle_zero_commits(issue, result)
        elif route == "fail_null_delivery":
            await self._handle_null_delivery(issue, result)
        await self._run_spec_compliance_review(issue, result)
        return state

    async def _flow_gate(self, state: FlowState) -> FlowState:
        """Convergence gate: record the retry-vs-HITL disposition (#10682).

        The epic's ``gate(retry <= max | route-to-HITL)`` node. It is read-only
        here: it records ``state['disposition']`` (``"retry"`` for a converging
        failure that re-queues as ``hydraflow-ready`` for a corrective attempt,
        ``"escalate"`` for a thrashing / cap-reached one). Enforcement stays in
        ``decompose`` (``_check_attempt_cap``), ``no-progress-abort`` and
        ``zero-commit-abort`` so the HITL escalation fires exactly once (never
        double-firing here).
        """
        issue = state["issue"]
        attempts = self._state.get_issue_attempts(issue.id)
        escalate = (
            self._should_abort_no_progress(issue)
            or attempts >= self._config.max_issue_attempts
        )
        state["disposition"] = "escalate" if escalate else "retry"
        return state

    async def _flow_open_pr(self, state: FlowState) -> FlowState:
        """Push + PR resolution + review handoff (#10682 open-pr node).

        Reproduces the pre-refactor push/finalize tail of
        ``_handle_implementation_result``: push the branch (success or retry),
        resolve/recover the PR and hand off to review, flag requirements gaps,
        and mark the issue. A fully-resolved early return (no-PR fallback /
        zero-diff escalation) or a success ends the walk at ``done``; a failed
        push falls through to ``spec-verify`` for the two-stage review.
        """
        issue = state["issue"]
        result = state["result"]
        is_retry = state["is_retry"]

        # Surface B of the #11457 window: the issue can also close DURING
        # the (minutes-long) build. Re-check before pushing so a resolved
        # issue never opens the duplicate PR — the commit cost is already
        # spent, but the PR, its CI, and the review round are not.
        if await self._issue_resolved_elsewhere(issue.id):
            state["result"] = await self._abandon_resolved_issue(
                issue, state["branch"], at="open-pr"
            )
            state["_stop"] = True
            return state

        # Fresh failed attempts skip the push entirely — partial commits never
        # land on origin. Cycling retries reset the worktree to main. Retries
        # with review feedback push so the existing PR sees the iteration.
        if result.workspace_path and (result.success or is_retry):
            pushed = await self._prs.push_branch(
                Path(result.workspace_path), result.branch
            )
            if pushed:
                early_return = await self._handle_successful_push(
                    issue, result, is_retry
                )
                if early_return is not None:
                    state["result"] = early_return
                    state["_stop"] = True
                    return state

        if result.success and result.transcript:
            await self._flag_requirements_gaps(issue, result.transcript)

        self._state.mark_issue(issue.id, "success" if result.success else "failed")
        return state

    @staticmethod
    async def _flow_done(state: FlowState) -> FlowState:
        """Terminal sink for the implement flow (#10682).

        A no-op join point so every path — the happy walk and each fail-closed
        early exit — ends at one observable terminal carrying the final
        ``result``.
        """
        return state
