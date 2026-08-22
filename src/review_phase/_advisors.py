"""Advisor (pre-flight / post-verify) slice of ``ReviewPhase``.

Extracted VERBATIM from ``_phase.py`` (god-class decomposition, Refs #11547)
as a mixin — the same shape ``_visual_gate.py`` took in the #10840 pass.
``ReviewPhase`` inherits it, so every method here still resolves as an
attribute of ``ReviewPhase`` and instance/class-level patching in tests still
lands.

One concern: the review advisors — building the post-verify runner, obtaining
the pre-flight ``ReviewPlan`` before the executor runs, invoking the
post-verify advisor for a surface, rendering its transcript back to the
executor, and the product-track pre-merge spec check that rides the same
machinery. The ADR-surface variants live in ``_adr.py``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from judge_calibration import judge_verdict_ledger_path, subject_for_pr

from ._common import _AdvisorRole

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from events import EventBus
    from models import PRInfo, Task
    from ports import PRPort
    from review_advisor import PostVerifyResult, ReviewPlan
    from reviewer import ReviewRunner
    from state import StateTracker

logger = logging.getLogger("hydraflow.review_phase")


class AdvisorMixin:
    """Advisor (pre-flight / post-verify) slice of ``ReviewPhase``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``ReviewPhase.__init__`` or by a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would win over the real
    # implementation whenever this mixin precedes the implementing one
    # in ``ReviewPhase``'s MRO.
    # ------------------------------------------------------------------
    _advisor_attempt: dict[int, int]
    _advisor_pre_flight_plan: dict[tuple[str, int], ReviewPlan]
    _advisor_results: dict[int, list[Any]]
    _bus: EventBus
    _config: HydraFlowConfig
    _factory_bound_files_cache: frozenset[str] | None
    _post_verify_runner: Any
    _prs: PRPort
    _reviewers: ReviewRunner
    _state: StateTracker

    def _build_post_verify_runner(self) -> Any:
        """Build the runner adapter the PostVerifyAdvisor dispatches into.

        Production path: routes through ``self._reviewers._execute`` (the
        existing review-runner harness — same plumbing used by
        ``_run_pre_merge_spec_check``).

        MockWorld path: ``self._reviewers`` is the FakeReviewRunner whose
        ``.parent`` is the FakeLLM. We extract the issue number from the
        prompt (emitted by ``PostVerifyAdvisor._build_prompt`` when
        ``PostVerifyInput.issue_number`` is set) and pop the scripted advisor
        result keyed by ``(issue_number, f"post_verify:{lens}")`` (the
        lens-tagged role, e.g. ``"post_verify:correctness"``).

        Dispatch is duck-typed on ``hasattr(self._reviewers, "_execute")``:
        production ``ReviewRunner`` provides it via ``BaseRunner``; the
        MockWorld fake does not. T9 keeps this routing simple — T10 will
        revisit if/when bounded retry needs richer wiring.
        """
        parent = self

        class _PostVerifyRunner:
            async def run(
                self,
                *,
                model: str,
                subagent_type: str,
                prompt: str,
                role: _AdvisorRole,
            ) -> str:
                # noqa is intentional — `subagent_type` is part of the
                # _AdvisorSubagentRunner protocol; production path does not
                # forward it (TranscriptEventData has no slot for it), but
                # MockWorld path keys advisor scripts by role only.
                _ = subagent_type
                reviewers = parent._reviewers

                # MockWorld dispatch: scenarios attach a FakeLLM via a
                # sentinel attribute (_mockworld_fake_llm) to route advisor
                # calls past the production ReviewRunner._execute (which
                # would hit a real Claude subprocess). Production reviewers
                # never carry this sentinel.
                #
                # Use ``vars()`` (not ``getattr``) for the presence check —
                # ``unittest.mock.AsyncMock`` auto-vivifies any attribute
                # access into a child mock, which would route every test
                # using an AsyncMock-based reviewer into the MockWorld
                # branch and return a coroutine-as-payload. Real MockWorld
                # scenarios set the sentinel as an instance attribute
                # (see tests/scenarios/fakes/mock_world.py), so checking
                # ``__dict__`` cleanly distinguishes them.
                instance_dict = getattr(reviewers, "__dict__", None) or {}
                fake_llm = instance_dict.get("_mockworld_fake_llm")
                if fake_llm is not None and getattr(
                    fake_llm, "_is_fake_adapter", False
                ):
                    import re  # noqa: PLC0415

                    if not hasattr(fake_llm, "pop_advisor_result"):
                        return ""
                    match = re.search(r"^Issue:\s*(\d+)\s*$", prompt, re.MULTILINE)
                    issue_number = int(match.group(1)) if match else 0
                    # Role resolution: prefer the explicit ``role`` parameter
                    # passed by the advisor (T24.5 closed I1+I2). Mid-flight
                    # calls dispatch from inside the executor's session via
                    # the Task tool, which doesn't thread through this
                    # protocol — those prompts carry the
                    # ``MidFlightAdvisor.SENTINEL`` HTML-comment marker as
                    # their first line, so we detect that explicitly. This
                    # is a forward-only marker that won't naturally appear
                    # in PR bodies, specs, or user content (unlike the
                    # pre-T24.5 ``## Mid-flight consult`` header substring
                    # which false-positived on advisor-pattern PRs whose
                    # bodies documented the format).
                    from review_advisor import (  # noqa: PLC0415
                        MidFlightAdvisor,
                    )

                    if MidFlightAdvisor.SENTINEL in prompt:
                        resolved_role: _AdvisorRole = "mid_flight"
                    else:
                        resolved_role = role
                    result = fake_llm.pop_advisor_result(issue_number, resolved_role)
                    if isinstance(result, str):
                        return result
                    return result or ""

                # Production path: thread through the same review-runner
                # harness used by _run_pre_merge_spec_check.
                from agent_cli import build_agent_command  # noqa: PLC0415

                cmd = build_agent_command(
                    tool=parent._config.review_tool,
                    model=model,
                    disallowed_tools="Write,Edit,NotebookEdit",
                    isolate_user_settings=True,
                )
                return await reviewers._execute(
                    cmd,
                    prompt,
                    parent._config.repo_root,
                    {"source": "advisor"},
                )

        return _PostVerifyRunner()

    async def _run_pre_flight_advisor(
        self,
        pr: PRInfo,
        task: Task,
        diff: str,
        surface: str = "pr_review",
    ) -> None:
        """Run :class:`PreFlightAdvisor` when the composite trigger fires.

        Stashes the resulting :class:`ReviewPlan` under
        ``self._advisor_pre_flight_plan[(surface, pr.number)]`` (T38) so
        downstream call sites (the executor's review prompt + the
        post-verify advisor's input) can consume it without a second
        invocation. Best-effort writes a JSON scratchpad to
        ``review_logs/<pr>/preflight.json`` for operator debugging —
        failures there must not break the pipeline.

        No-ops when:
          * The selected ``surface`` or pre_flight role is kill-switched off.
          * The composite trigger returns False (trivial/docs-only diffs
            without prior fix attempts and no critical-path touches).
          * The advisor returns ``None`` (degraded path — runner or parse
            error). The executor proceeds without a plan; the contract is
            "advisor is advisory" per the spec.

        ``surface`` defaults to ``"pr_review"`` for back-compat (T24.7 prep
        for Phase 4 multi-surface wiring); other surfaces (``adr_review``,
        ``visual_gate``, etc.) pass the surface name explicitly.

        Function-local imports keep the dependency on ``review_advisor``
        contained to where it's used and avoid the auto-lint hook stripping
        an "unused" top-level import.
        """
        from review_advisor import (  # noqa: PLC0415
            PreFlightAdvisor,
            PreFlightInput,
            build_surface_config,
            diff_stats_from_text,
            is_advisor_enabled,
        )

        surface_cfg = build_surface_config(surface)
        if (
            not surface_cfg.pre_flight_enabled
            or surface_cfg.pre_flight_trigger is None
            or not is_advisor_enabled(surface, "pre_flight")
        ):
            return

        diff_stats = diff_stats_from_text(diff)
        from review_advisor import PRContext, compute_blast_radius  # noqa: PLC0415

        blast = compute_blast_radius(diff_stats)
        self._state.set_review_blast_radius(task.id, blast)
        logger.debug(
            "review blast_radius=%s pr=%d issue=%d paths=%d lines=%d",
            blast,
            pr.number,
            task.id,
            len(diff_stats.changed_paths),
            diff_stats.lines_changed,
        )

        pr_ctx = PRContext(prior_fix_attempts=self._advisor_attempt.get(pr.number, 0))
        if not surface_cfg.pre_flight_trigger.should_run(diff_stats, pr_ctx):
            return

        log_path = (
            self._config.repo_root
            / "review_logs"
            / str(pr.number)
            / "advisor_session.jsonl"
        )
        advisor = PreFlightAdvisor(
            runner=self._post_verify_runner,
            surface_config=surface_cfg,
            log_path=log_path,
            pr_number=pr.number,
            # #10836 phase 2: the PR path joins the escape ledger by PR.
            judge_verdict_ledger_path=judge_verdict_ledger_path(self._config.data_root),
            calibration_subject_id=subject_for_pr(pr.number),
        )
        # Human-on-the-loop continuous steering (ADR-0099 #4): the advisor
        # reviews the same issue as the executor, so live operator guidance
        # should reach its prompt too.
        human_guidance = self._state.get_human_steering(str(task.id)).guidance or ""
        try:
            plan = await advisor.run(
                PreFlightInput(
                    surface=surface,
                    diff=diff,
                    spec=task.body or None,
                    related_paths=diff_stats.changed_paths,
                    prior_attempts=self._advisor_attempt.get(pr.number, 0),
                    issue_number=task.id,
                    human_guidance=human_guidance,
                )
            )
        except Exception as exc:
            # Auth / credit errors are re-raised inside PreFlightAdvisor.run,
            # but per docs/wiki/dark-factory.md §2.2 the wrapper's broad
            # except must also reraise credit-exhausted / likely-bug errors
            # so the orchestrator sees infrastructure failures.
            from exception_classify import (  # noqa: PLC0415
                reraise_on_credit_or_bug,
            )

            reraise_on_credit_or_bug(exc)
            logger.warning(
                "pre_flight advisor errored for PR #%d — proceeding without plan",
                pr.number,
                exc_info=True,
            )
            return

        if plan is None:
            return
        self._advisor_pre_flight_plan[(surface, pr.number)] = plan
        scratchpad = (
            self._config.repo_root / "review_logs" / str(pr.number) / "preflight.json"
        )
        try:
            scratchpad.parent.mkdir(parents=True, exist_ok=True)
            scratchpad.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        except Exception:
            logger.debug("preflight scratchpad write failed", exc_info=True)

    async def _run_post_verify_for_surface(
        self,
        *,
        surface: str,
        diff: str,
        spec: str | None,
        executor_verdict_summary: str,
        executor_fix_diff: str | None = None,
        pre_flight_plan: ReviewPlan | None = None,
        attempt_number: int = 0,
        issue_number: int,
        log_pr_number: int | None = None,
        lens: Literal["correctness", "security", "spec"] | None = None,
        classification_paths: list[str] | None = None,
    ) -> PostVerifyResult | None:
        """Run a single post-verify advisor invocation for ``surface``.

        Returns the :class:`PostVerifyResult`, or ``None`` when the advisor
        was skipped (surface/role kill-switch off) or degraded (runner crash
        / parse error surfaced past ``reraise_on_credit_or_bug``). Callers
        layer their own disposition logic on top: binary-gate (block on
        VETO), advisory (downgrade VETO to APPROVE inside the advisor's
        ``run``), requeue (ADR), retry-loop (pr_review).

        Shared skeleton extracted from the five per-surface helpers (T35).
        Each helper now owns only the disposition logic specific to its
        surface; the surface-config lookup, kill-switch check, authority
        resolution (T29 self-modification guard), log path construction,
        :class:`PostVerifyAdvisor` instantiation, and
        ``reraise_on_credit_or_bug`` discipline (``docs/wiki/dark-factory.md``
        §2.2) all live here.

        Authority is resolved on every call, so the pr_review retry loop
        — which wraps this helper in a while-loop — re-checks
        :func:`resolve_post_verify_authority` per iteration. A fix that
        introduces or removes a self-modifying path is picked up on the
        next pass.

        ``log_pr_number`` defaults to ``None``; when supplied, the log
        path is keyed by the PR number, and ``PostVerifyAdvisor.pr_number``
        receives the PR number. When unset, both fall back to
        ``issue_number`` — the convention for surfaces with no PR (ADR
        review, wiki ingest).

        ``classification_paths`` (#10371) is threaded into
        :class:`PostVerifyInput` for blast-radius classification on surfaces
        whose ``diff`` is not a unified diff (no ``+++ b/`` headers) — most
        importantly ``adr_review``, whose ADR draft lives in the issue body.
        Defaults to ``None`` (empty), which keeps the ordinary diff-only
        classification path unchanged.
        """
        from review_advisor import (  # noqa: PLC0415
            PostVerifyAdvisor,
            PostVerifyInput,
            build_surface_config,
            is_advisor_enabled,
            resolve_post_verify_authority,
        )

        surface_cfg = build_surface_config(surface)
        if not surface_cfg.post_verify_enabled or not is_advisor_enabled(
            surface, "post_verify"
        ):
            return None

        # T29 self-modification guard — diffs touching advisor's own
        # implementation files force veto authority regardless of surface
        # config. Resolved on every call so a fix that introduces or
        # removes a self-modifying path is picked up on the next pass.
        authority = resolve_post_verify_authority(
            surface_config=surface_cfg,
            diff=diff,
        )

        log_key = log_pr_number if log_pr_number is not None else issue_number
        log_path = (
            self._config.repo_root
            / "review_logs"
            / str(log_key)
            / "advisor_session.jsonl"
        )
        # #10371 judge-independence budget + fail-visible dispatch. The ledger
        # + dashboard alarm are always live; the two flags gate the merge-
        # outcome-changing behaviours (opt-in until validated). Independence
        # resolution reads the configured cross-family judge model.
        from judge_calibration import judge_verdict_ledger_path
        from judge_independence import (
            factory_bound_source_files,
            independent_judge_model,
            ledger_path_for,
        )

        # ADR-0123 / #10851 mechanical backstop: source files an ADR governs with
        # `Binds: factory`/`both` are self-modification by declared direction,
        # catching gate-enablement config the substring enumeration under-includes.
        # Computed once per ReviewPhase (ADRs are stable within a run).
        factory_bound_files = getattr(self, "_factory_bound_files_cache", None)
        if factory_bound_files is None:
            from adr_index import scan_adr_directory

            factory_bound_files = factory_bound_source_files(
                scan_adr_directory(self._config.repo_root / "docs" / "adr")
            )
            self._factory_bound_files_cache = factory_bound_files

        advisor = PostVerifyAdvisor(
            runner=self._post_verify_runner,
            surface_config=surface_cfg,
            log_path=log_path,
            pr_number=log_key,
            authority_override=authority,
            ledger_path=ledger_path_for(self._config),
            event_bus=self._bus,
            judge_independence_enabled=self._config.judge_independence_enabled,
            self_mod_fail_closed_enabled=(
                self._config.judge_self_mod_fail_closed_enabled
            ),
            independent_model=independent_judge_model(self._config),
            factory_bound_files=factory_bound_files,
            judge_verdict_ledger_path=judge_verdict_ledger_path(self._config.data_root),
        )
        # Human-on-the-loop continuous steering (ADR-0099 #4): the advisor
        # reviews the same issue as the executor, so live operator guidance
        # should reach its prompt too.
        human_guidance = (
            self._state.get_human_steering(str(issue_number)).guidance or ""
        )
        try:
            return await advisor.run(
                PostVerifyInput(
                    surface=surface,
                    diff=diff,
                    spec=spec,
                    executor_verdict_summary=executor_verdict_summary,
                    executor_fix_diff=executor_fix_diff,
                    pre_flight_plan=pre_flight_plan,
                    attempt_number=attempt_number,
                    issue_number=issue_number,
                    lens=lens,
                    human_guidance=human_guidance,
                    classification_paths=classification_paths or [],
                )
            )
        except Exception as exc:
            # Per docs/wiki/dark-factory.md §2.2: the broad-except must
            # reraise credit-exhausted / likely-bug errors so the
            # orchestrator's higher layers see infrastructure failures
            # rather than burn the attempt budget against an exhausted
            # billing signal.
            from exception_classify import (  # noqa: PLC0415
                reraise_on_credit_or_bug,
            )

            reraise_on_credit_or_bug(exc)
            logger.warning(
                "post_verify advisor degraded surface=%s log_key=%s — %r",
                surface,
                log_key,
                exc,
            )
            return None

    def _render_advisor_transcript(self, pr_number: int) -> str:
        """Render the in-memory advisor disagreement transcript for ``pr_number``.

        Phase 2 builds the transcript from ``self._advisor_results``;
        T12 will replace this with a persistent ``advisor_session.jsonl``.
        """
        results = self._advisor_results.get(pr_number, [])
        parts: list[str] = []
        for i, r in enumerate(results, 1):
            parts.append(f"### Attempt {i}")
            parts.append(f"Verdict: {r.verdict}")
            parts.append(f"Reasoning: {r.reasoning}")
            for d in r.disagreements:
                parts.append(
                    f"  - [{d.severity}] executor said: {d.executor_claim}\n"
                    f"    advisor said: {d.advisor_assessment}"
                )
            if r.suggested_fix_direction:
                parts.append(f"Suggested direction: {r.suggested_fix_direction}")
            parts.append("")
        return "\n".join(parts)

    async def _run_pre_merge_spec_check(
        self, task: Task, diff: str, pr_number: int | None = None
    ) -> bool:
        """Run a lightweight spec-match check before merge.

        Returns True if the implementation matches the spec (proceed with merge).
        Returns False if significant gaps are found (block merge).

        ``pr_number`` (T25) is used to look up the pre-flight ReviewPlan from
        ``self._advisor_pre_flight_plan`` so the post-verify advisor for the
        ``pre_merge_spec_check`` surface can piggyback on ``pr_review``'s
        plan. Defaults to ``None`` for back-compat with regression tests that
        invoke the function directly. T38 (M7) keys the dict by
        ``(surface, identifier)``; the piggyback lookup explicitly uses
        ``("pr_review", pr_number)`` because ``pre_merge_spec_check`` itself
        never produces a plan (``pre_flight_enabled=False``).
        """
        from spec_match import (  # noqa: PLC0415
            build_self_review_prompt,
            extract_spec_match,
        )

        diff_summary = diff[:5000] if len(diff) > 5000 else diff
        prompt = build_self_review_prompt(task, diff_summary)

        try:
            from agent_cli import build_agent_command  # noqa: PLC0415

            cmd = build_agent_command(
                tool=self._config.review_tool,
                model=self._config.review_model,
                disallowed_tools="Write,Edit,NotebookEdit",
                isolate_user_settings=True,
            )
            transcript = await self._reviewers._execute(
                cmd,
                prompt,
                self._config.repo_root,
                {"issue": task.id, "source": "spec-check"},
            )
            result = extract_spec_match(transcript)
            verdict = str(result.get("verdict", "UNKNOWN"))

            if result.get("content"):
                await self._prs.post_comment(
                    task.id,
                    f"## Pre-Merge Spec Check\n\n{result['content']}",
                )

            executor_match = verdict != "MISMATCH"

            # T25: pre_merge_spec_check post-verify advisor — second-opinion
            # gate on the executor's verdict. The advisor sees the spec, the
            # diff, and the executor's verdict summary, and can VETO the merge
            # even when the executor's verdict was MATCH. Piggybacks on
            # ``pr_review``'s pre-flight plan when present (per spec tiering
            # matrix; pre_merge_spec_check has pre_flight_enabled=False).
            #
            # No bounded retry loop here: pre_merge_spec_check is a one-shot
            # binary gate, not a fix-and-iterate cycle. If post-verify VETOes,
            # we return False to block the merge directly; the caller (in
            # _run_post_review_actions) flips the ReviewResult to
            # REQUEST_CHANGES. Future work: fold in retry semantics if the
            # spec-check ever grows a fix loop.
            advisor_blocked = await self._run_pre_merge_spec_check_advisor(
                task=task,
                diff=diff,
                executor_verdict_summary=verdict,
                pr_number=pr_number,
            )
            if advisor_blocked:
                return False

            if verdict == "MISMATCH":
                logger.warning(
                    "Issue #%d spec-match MISMATCH — blocking merge", task.id
                )
                return False
            return executor_match
        except Exception as exc:
            # Fatal infrastructure errors (auth, credit, likely-bug) must
            # propagate so the pipeline's auth-retry / credit-pause / crash
            # handling layers can react. Soft failures block the merge
            # instead of silently approving — the merge gate must be
            # fail-closed, not fail-open (issue #6357).
            #
            # #11618/#11626: this used to restate the fatal set as a literal
            # ``AuthenticationError | CreditExhaustedError`` re-raise followed
            # by the six likely-bug types. That restatement is exactly the
            # drift the centralized set exists to prevent, so it now defers to
            # ``FATAL_EXCEPTIONS`` — same two infra errors, the identical six
            # likely-bug types, plus ``MemoryError``, which the canonical set
            # has always classed as fatal and which this handler was silently
            # absorbing into a merge block. Matches the two sibling advisor
            # handlers in this module.
            from exception_classify import (  # noqa: PLC0415
                reraise_on_credit_or_bug,
            )

            reraise_on_credit_or_bug(exc)
            # Credit/auth-looking string matches coming through non-SDK paths
            # (e.g. wrapped by review runner). Keep these as raising too —
            # the message is the only signal.
            msg = str(exc)
            if "CreditExhaustedError" in msg or "AuthenticationError" in msg:
                raise
            logger.warning(
                "Spec-match check failed for #%d — blocking merge to avoid fail-open",
                task.id,
                exc_info=True,
            )
            return False

    async def _run_pre_merge_spec_check_advisor(
        self,
        *,
        task: Task,
        diff: str,
        executor_verdict_summary: str,
        pr_number: int | None,
    ) -> bool:
        """Run PostVerifyAdvisor for the ``pre_merge_spec_check`` surface.

        Returns ``True`` when the advisor VETOes (caller must block the merge);
        ``False`` when the advisor APPROVEs, the surface/role kill-switches
        are off, or the advisor degrades on a non-fatal error.

        The pre_merge_spec_check surface is a binary gate — there is no
        fix-and-iterate retry loop here. If VETO occurs, the merge is blocked
        directly; the executor's existing fail-closed behaviour on MISMATCH
        is preserved. ``reraise_on_credit_or_bug`` discipline is preserved
        inside :meth:`_run_post_verify_for_surface` per
        ``docs/wiki/dark-factory.md`` §2.2.
        """
        # Piggyback on pr_review's pre-flight plan when present (per spec
        # tiering matrix). pre_merge_spec_check has pre_flight_enabled=False
        # so it never produces its own plan — the lookup key is therefore
        # ("pr_review", pr_number), NOT ("pre_merge_spec_check", pr_number).
        # (T38: dict keyed by (surface, identifier).)
        pre_flight_plan = (
            self._advisor_pre_flight_plan.get(("pr_review", pr_number))
            if pr_number is not None
            else None
        )

        pv_result = await self._run_post_verify_for_surface(
            surface="pre_merge_spec_check",
            diff=diff,
            spec=task.body or None,
            executor_verdict_summary=executor_verdict_summary,
            pre_flight_plan=pre_flight_plan,
            issue_number=task.id,
            log_pr_number=pr_number,
        )
        if pv_result is None:
            # Degraded path or kill-switch off: let the executor's verdict
            # stand. The executor's existing fail-closed semantics on
            # MISMATCH still block bad merges; the advisor is a strict
            # tightening on MATCH-shaped verdicts only.
            return False

        if pv_result.verdict == "VETO":
            logger.warning(
                "Issue #%d pre_merge_spec_check VETO from advisor — blocking merge",
                task.id,
            )
            return True
        return False
