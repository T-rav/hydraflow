"""Build preparation and the agent run itself, for ``ImplementPhase``.

Extracted VERBATIM from ``src/implement_phase.py`` (god-class
decomposition, Refs #11547) as a mixin — the shape ``review_phase/`` already
uses. ``ImplementPhase`` inherits it, so every method here still resolves as
an attribute of ``ImplementPhase`` and instance/class-level patching in tests
still lands.

One concern: everything that turns a ready issue into one agent build — the
durable cross-actor build claim (#10168), the prompt context (known CI traps,
plan-phase adversarial carryover, the ADR plan fallback), the complexity-tiered
spawn budget (#11568), the worktree/branch setup, the ``AgentRunner`` call, and
the metrics/meta recorded from its result.
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import TYPE_CHECKING

from adr_utils import is_adr_issue_title, next_adr_number
from harness_insights import (
    FailureCategory,
    format_known_traps_for_prompt,
    top_failure_categories,
)
from implement_timeout import tiered_implement_timeout
from issue_cache import classification_complexity
from models import PipelineStage
from phase_utils import record_harness_failure

from ._common import _pinned_adequacy_demand

if TYPE_CHECKING:
    from pathlib import Path

    from agent import AgentRunner
    from beads_manager import BeadsManager
    from config import HydraFlowConfig
    from harness_insights import HarnessInsightStore
    from issue_cache import IssueCache
    from models import Task, WorkerResult, WorkerResultMeta
    from ports import IssueStorePort, PRPort, WorkspacePort
    from state import StateTracker
    from task_source import TaskTransitioner

logger = logging.getLogger("hydraflow.implement_phase")


class ImplementBuildMixin:
    """Build preparation and the agent run itself, for ``ImplementPhase``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``ImplementPhase.__init__`` or by
    # a sibling mixin. The method declarations are TYPE_CHECKING-only
    # on purpose: a runtime ``...`` body would win over the
    # real implementation whenever this mixin precedes the
    # implementing one in ``ImplementPhase``'s MRO.
    # ------------------------------------------------------------------
    _agents: AgentRunner
    _beads_manager: BeadsManager | None
    _config: HydraFlowConfig
    _harness_insights: HarnessInsightStore | None
    _issue_cache: IssueCache | None
    _prs: PRPort
    _state: StateTracker
    _store: IssueStorePort
    _transitioner: TaskTransitioner
    _workspaces: WorkspacePort

    if TYPE_CHECKING:

        async def _complete_beads_after_success(
            self, mapping: dict[str, str], wt_path: Path
        ) -> bool | None: ...  # provided by _beads

        async def _create_beads_in_worktree(
            self, issue: Task, wt_path: Path
        ) -> dict[str, str] | None: ...  # provided by _beads

    async def _claim_issue(self, issue_number: int) -> None:
        """Stamp the durable build-claim marker on *issue_number* (#10168).

        Adds ``in_progress_label`` the moment a build STARTS on a ready issue.
        The label coexists with ``hydraflow-ready`` (it is not a stage) and
        advertises "being built" to any external observer of GitHub labels —
        a second factory instance, a parallel operator session, or an
        out-of-band Agent dispatch — so they skip the issue instead of
        double-picking it (the #10141 cross-actor collision class).

        Best-effort: a GitHub hiccup must never block the build (dark-factory
        contract). The in-process ``IssueStore`` guards still protect the
        current process even if the durable stamp fails.
        """
        try:
            await self._prs.add_labels(issue_number, self._config.in_progress_label)
        except Exception:
            logger.warning(
                "Issue #%d: failed to stamp in-progress build claim (continuing)",
                issue_number,
                exc_info=True,
            )

    async def _release_claim(self, issue_number: int) -> None:
        """Clear the build-claim marker on any build exit (#10168).

        On the success path the ``ready → review`` swap already removed the
        claim (it is in ``all_pipeline_labels``); this remove is then a no-op.
        On abandon/failure the issue stays at ``hydraflow-ready``, so removing
        the claim here is what makes it re-pickable — an issue can never get
        stuck claimed. Best-effort, like :meth:`_claim_issue`.
        """
        for label in self._config.in_progress_label:
            try:
                await self._prs.remove_label(issue_number, label)
            except Exception:
                logger.warning(
                    "Issue #%d: failed to clear in-progress build claim '%s'",
                    issue_number,
                    label,
                    exc_info=True,
                )

    def _known_traps_section(self) -> str:
        """Render the harness-insights Known CI Traps section (#9858).

        Cached per phase instance for one hour — the failure distribution
        moves slowly and run_batch may spawn many agents per tick. Fails
        open to "" so a store hiccup never blocks implementation.
        """
        now = time.monotonic()
        cached = getattr(self, "_known_traps_cache", None)
        if cached is not None and now - cached[0] < 3600:
            return cached[1]
        section = ""
        if self._harness_insights is not None:
            try:
                entries = top_failure_categories(self._harness_insights._failures_path)
                section = format_known_traps_for_prompt(entries)
            except (OSError, ValueError) as exc:
                logger.debug("known-traps render failed: %s", exc)
        self._known_traps_cache = (now, section)
        return section

    def _log_adversarial_carryover(self, issue: Task) -> None:
        """Log CRITICAL/HIGH carryover concerns surfaced during plan phase.

        Dark-factory contract (Task 7 of earlier-adversarial pipeline):
        implement_phase READS the per-issue ``AdversarialState`` so the
        operator (and downstream tooling) can see pending concerns, but
        it MUST NOT block on them. Concerns are logged at INFO level
        and the implementation proceeds.

        Safe to call when no state has been persisted — the read
        returns ``None`` and the method is a no-op.
        """
        adv = self._state.get_adversarial_state(issue.id)
        if adv is None:
            return
        loud_concerns = [
            c for c in adv.pending_concerns if c.severity in {"CRITICAL", "HIGH"}
        ]
        if not loud_concerns:
            return
        lines = [
            f"  - [{c.id}|{c.severity}|{c.raised_in_stage}] {c.concern}"
            for c in loud_concerns
        ]
        logger.info(
            "Adversarial carryover for issue #%d (%d %s concern(s)) — "
            "forwarding to implementation per dark-factory contract:\n%s",
            issue.id,
            len(loud_concerns),
            "CRITICAL/HIGH",
            "\n".join(lines),
        )

    def _implement_timeout(self, issue: Task) -> int:
        """Complexity-tiered spawn budget for *issue* (#11568).

        Reads triage's ``complexity_score`` from the shared IssueCache
        classification record (the field #11304/#11305 tier on) and maps it
        through :func:`implement_timeout.tiered_implement_timeout` with
        ``agent_timeout`` as the ceiling. Unknown → the ceiling, so an
        unscored issue never gets a shorter budget than it did before.
        """
        complexity = classification_complexity(self._issue_cache, issue.id)
        ceiling = int(self._config.agent_timeout)
        timeout = tiered_implement_timeout(complexity, ceiling)
        if timeout != ceiling:
            logger.info(
                "Issue #%d: implement timeout %ds (complexity %s, ceiling %ds)",
                issue.id,
                timeout,
                complexity,
                ceiling,
            )
        return timeout

    def _read_plan_for_recording(self, issue_number: int) -> str:
        """Read the plan file for *issue_number*, returning empty string on failure."""
        plan_path = self._config.plans_dir / f"issue-{issue_number}.md"
        try:
            return plan_path.read_text()
        except OSError:
            return ""

    def _prepare_adr_plan(self, issue: Task) -> None:
        """Seed a deterministic ADR execution plan when an ADR issue lacks one."""
        if not is_adr_issue_title(issue.title):
            return

        plan_path = self._config.plans_dir / f"issue-{issue.id}.md"
        if plan_path.exists():
            return

        # Reserve a unique ADR number by scanning the primary repo (not the
        # worktree copy) and the in-process assignment set.
        primary_adr_dir = self._config.repo_root / "docs" / "adr"
        adr_number = next_adr_number(primary_adr_dir)
        adr_number_str = f"{adr_number:04d}"

        body = issue.body.strip() or "No ADR draft body provided."
        plan_text = (
            "## Implementation Plan\n\n"
            f"1. Create a single ADR markdown file named "
            f"`docs/adr/{adr_number_str}-<slug>.md` (ADR number "
            f"**{adr_number_str}** is pre-assigned — do NOT pick a different "
            f"number).\n"
            "2. Preserve and refine the ADR sections (`Context`, `Decision`, "
            "`Consequences`) using the issue draft as source material.\n"
            "3. Ensure the ADR content is actionable and concrete enough for "
            "review (explicit decision, tradeoffs, and impact).\n"
            "4. Add/update references so the ADR links back to this issue.\n"
            "   - Anywhere in the ADR (Related, Context, Decision, Consequences), "
            "cite source files by function/class name only "
            "(e.g. `src/config.py:_resolve_base_paths`). Do NOT include line numbers — "
            "they become stale as source files change.\n"
            "5. **Do NOT create tests for ADR markdown content.** ADRs are "
            "documentation — never add `test_adr_*.py` files that assert on "
            "headings, status, or prose.\n\n"
            "## ADR Draft From Issue\n\n"
            f"{body}\n"
        )
        try:
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text(plan_text)
            logger.info(
                "Prepared ADR implementation plan fallback for issue #%d at %s",
                issue.id,
                plan_path,
            )
        except OSError:
            logger.warning(
                "Failed to prepare ADR plan fallback for issue #%d",
                issue.id,
                exc_info=True,
            )

    async def _setup_worktree_and_branch(
        self, issue: Task, branch: str, *, reset_for_retry: bool = False
    ) -> Path:
        """Ensure worktree exists/resumed and branch is pushed.

        When *reset_for_retry* is True, resets an existing worktree to
        ``origin/main`` to discard stale state from a prior failed attempt.
        """
        wt_path = self._config.workspace_path_for_issue(issue.id)
        if wt_path.is_dir():
            if reset_for_retry:
                logger.info(
                    "Resetting worktree to clean state for issue #%d retry",
                    issue.id,
                )
                try:
                    await self._workspaces.reset_to_main(wt_path)
                except (RuntimeError, OSError):
                    logger.warning(
                        "Worktree reset failed for issue #%d — continuing with existing state",
                        issue.id,
                        exc_info=True,
                    )
            else:
                logger.info("Resuming existing worktree for issue #%d", issue.id)
        else:
            wt_path = await self._workspaces.create(issue.id, branch)
        self._state.set_workspace(issue.id, str(wt_path))
        await self._prs.push_branch(wt_path, branch, force=reset_for_retry)
        await self._transitioner.post_comment(
            issue.id,
            f"**Branch:** [`{branch}`](https://github.com/"
            f"{self._config.repo}/tree/{branch})\n\n"
            f"Implementation in progress.",
        )
        return wt_path

    async def _record_impl_metrics(
        self, issue: Task, result: WorkerResult, review_feedback: str
    ) -> None:
        """Record quality-fix-attempt, duration, harness metrics to state/store."""
        if review_feedback:
            self._state.clear_review_feedback(issue.id)
        if result.duration_seconds > 0:
            self._state.record_implementation_duration(result.duration_seconds)
        if result.quality_fix_attempts > 0:
            self._state.record_quality_fix_rounds(result.quality_fix_attempts)
            for _ in range(result.quality_fix_attempts):
                self._state.record_stage_retry(issue.id, "quality_fix")
            record_harness_failure(
                self._harness_insights,
                issue.id,
                FailureCategory.QUALITY_GATE,
                f"Quality fix needed: {result.quality_fix_attempts} round(s). "
                f"Error: {result.error or 'none'}",
                stage=PipelineStage.IMPLEMENT,
            )
        # Only write a quality_fix stage record when a fix round actually
        # happened. Writing unconditionally (including count == 0) created an
        # empty stage_state["quality_fix"] entry for every issue; retrospective
        # reads via ConvergenceLedger.get_attempts() already default to 0 for
        # a missing stage, so skipping the zero-count write is a no-op for
        # readers.
        if result.quality_fix_attempts > 0:
            self._state.set_quality_fix_attempts(issue.id, result.quality_fix_attempts)
        meta: WorkerResultMeta = {
            "pre_quality_review_attempts": result.pre_quality_review_attempts,
            "duration_seconds": result.duration_seconds,
            "error": result.error,
            "commits": result.commits,
        }
        # #11644: pin the demand the adequacy gate actually made, so the next
        # attempt is judged against THIS bar rather than a freshly-sampled one.
        # Only the blocking findings ride forward — advisory ones did not
        # reject this run and must not become the next run's bar.
        pinned = _pinned_adequacy_demand(result)
        if pinned:
            meta["test_adequacy_findings"] = pinned
        self._state.set_worker_result_meta(issue.id, meta)

    async def _run_implementation(
        self,
        issue: Task,
        branch: str,
        worker_id: int,
        review_feedback: str,
    ) -> WorkerResult:
        """Set up worktree, push branch, run agent, record metrics."""
        # Retrieve prior failure context for retry feedback
        last_meta = self._state.get_worker_result_meta(issue.id)
        prior_failure = ""
        # #11644: the demand the previous attempt's adequacy gate stated. Rides
        # the same seam as prior_failure and under the same condition — during a
        # review-feedback retry the prior gate verdict is stale, so no pin.
        pinned_adequacy: list[str] = []
        reset_for_retry = bool(review_feedback)  # review-feedback retries always reset
        # Only inject prior failure context for cycling retries (no active review feedback).
        # During review-feedback retries the prior error is stale — the agent should
        # focus on reviewer comments, not a potentially-resolved quality gate error.
        if last_meta and not review_feedback:
            pinned_adequacy = [
                f
                for f in last_meta.get("test_adequacy_findings") or []
                if isinstance(f, str) and f.strip()
            ]
            prior_error = last_meta.get("error") or ""
            # ADR-0063 W5: spec-compliance gaps from the prior attempt's
            # post-failure review take priority — they describe *what* was
            # missing (or wrong), which is more actionable than the runner's
            # error string. Both are included when both exist.
            spec_gaps = last_meta.get("spec_review_gaps") or ""
            if spec_gaps and prior_error:
                prior_failure = f"{spec_gaps}\n\nRunner error: {prior_error}"
                reset_for_retry = True
            elif spec_gaps:
                prior_failure = spec_gaps
                reset_for_retry = True
            elif prior_error:
                prior_failure = prior_error
                reset_for_retry = True

        wt_path = await self._setup_worktree_and_branch(
            issue, branch, reset_for_retry=reset_for_retry
        )

        # Human-on-the-loop continuous steering (ADR-0099 #4): fold live
        # operator guidance into the prompt. Reference signal only — never
        # blocking; empty when the feature is off or no guidance was posted.
        human_guidance = self._state.get_human_steering(str(issue.id)).guidance or ""

        # Capture items.jsonl hash before agent runs (for outcome tracking)
        import hashlib  # noqa: PLC0415

        items_path = self._config.memory_dir / "items.jsonl"
        digest_hash = ""
        if items_path.exists():
            with contextlib.suppress(OSError):
                digest_hash = hashlib.sha256(items_path.read_bytes()).hexdigest()[:16]
        self._state.set_digest_hash(issue.id, digest_hash)

        # Copy architecture diagrams from /tmp into the worktree so the
        # implementer agent has full architectural context on disk.
        from planner import PlannerRunner  # noqa: PLC0415

        n_diagrams = PlannerRunner.copy_diagrams_to_workspace(issue.id, wt_path)
        if n_diagrams:
            logger.info(
                "Copied %d diagram file(s) into workspace for #%d",
                n_diagrams,
                issue.id,
            )
            PlannerRunner.cleanup_diagrams(issue.id)

        # Enrich the task with comments so the agent can find the plan
        # comment posted by the planner.  The IssueStore bulk fetch
        # does not include comment bodies.
        issue = await self._store.enrich_with_comments(issue)

        # Create the bead task graph in THIS worktree's canonical JSONL store.
        # Agent prompts reference these IDs but never invoke the database-backed
        # bd CLI; the planner no longer creates beads in a separate host store.
        bead_mapping: dict[str, str] | None = None
        if self._beads_manager is not None:
            bead_mapping = await self._create_beads_in_worktree(issue, wt_path)

        run_kwargs: dict[str, object] = {
            "worker_id": worker_id,
            "review_feedback": review_feedback,
            "prior_failure": prior_failure,
            "human_guidance": human_guidance,
            # #9858: recurring repo failure classes from harness-insights,
            # rendered once and injected so agents stop re-hitting
            # documented CI traps (ratchet, arch-regen, ...).
            "known_traps": self._known_traps_section(),
            # Diverse-retry: the agent frames its strategy-delta directive
            # as "attempt N of M" (rendered only when prior_failure is set).
            "attempt_number": self._state.get_issue_attempts(issue.id),
            # #11568: complexity-tiered wall-clock budget for the build spawn;
            # ``agent_timeout`` remains the ceiling inside the runner.
            "timeout_s": self._implement_timeout(issue),
            # #11644: judge this retry's adequacy verdict against the demand
            # the previous attempt stated, not a freshly-sampled one.
            "pinned_adequacy_findings": pinned_adequacy,
        }
        if bead_mapping:
            run_kwargs["bead_mapping"] = bead_mapping

        # Allocate a trace run id and set the tracing context on the agent
        # runner so its _execute calls build a TraceCollector.
        from trace_rollup import write_phase_rollup  # noqa: PLC0415
        from tracing_context import TracingContext, source_to_phase  # noqa: PLC0415

        phase = source_to_phase("implementer")
        run_id = self._state.begin_trace_run(issue.id, phase)
        self._agents.set_tracing_context(
            TracingContext(
                issue_number=issue.id,
                phase=phase,
                source="implementer",
                run_id=run_id,
            )
        )

        try:
            result = await self._agents.run(
                issue,
                wt_path,
                branch,
                **run_kwargs,  # type: ignore[arg-type]
            )
        finally:
            self._agents.clear_tracing_context()
            # Roll up the subprocess traces whether the run succeeded or failed.
            try:
                write_phase_rollup(
                    config=self._config,
                    issue_number=issue.id,
                    phase=phase,
                    run_id=run_id,
                )
            except Exception:
                logger.warning(
                    "Phase rollup failed for issue #%d", issue.id, exc_info=True
                )
            self._state.end_trace_run(issue.id, phase)

        if (
            result.success
            and bead_mapping
            and self._beads_manager is not None
            and not self._config.dry_run
        ):
            lifecycle_changed = await self._complete_beads_after_success(
                bead_mapping, wt_path
            )
            if lifecycle_changed is None:
                result.success = False
                result.error = "Failed to finalize worktree Beads lifecycle"
            elif not await self._agents.commit_pending(issue, wt_path):
                result.success = False
                result.error = "Failed to commit finalized worktree Beads lifecycle"

        await self._record_impl_metrics(issue, result, review_feedback)

        return result
