"""decompose_or_escalate — the auto-agent's decompose-before-HITL terminal.

ADR-0105 §Decision(1): at both places the auto-agent applies `human-required`
(`auto_agent_preflight_loop.py`'s attempt-cap pre-check, `preflight/decision.py`'s
`apply_decision` exhaustion + `_LABEL_MAP` needs_human/fatal path), this module
is called FIRST. Only when it declines (returns ``"human-required"``) does the
caller apply today's ADR-0084 behavior unchanged; when it decomposes, the
stuck issue is superseded by an epic + children and `human-required` is never
added.

This is the sole place `IssueDecomposer` and `DecompositionCouncil` are wired
together for the stall path (both are otherwise only exercised directly by
unit tests). Depth is resolved from any existing epic that already claims
this issue as a child (`EpicState.decomposition_depth + 1`) so a
re-decomposed auto-child's lineage is correctly bounded by
`config.max_decomposition_depth` — the same counter intake-triage decomposition
increments (ADR-0105 §4).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from decomposition_docs import gather_decomposition_docs
from exception_classify import reraise_on_credit_or_bug
from false_close import closing_issue_refs
from models import Task

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from decomposition_council import DecompositionCouncil
    from issue_decomposer import IssueDecomposer
    from preflight.context import PreflightContext

logger = logging.getLogger("hydraflow.preflight.decompose_terminal")

DECOMPOSED = "decomposed"
HUMAN_REQUIRED = "human-required"

# Bounds on how much of the stall evidence goes into the council prompt —
# mirrors decomposition_council.py's own task-body truncation (5000 chars);
# kept smaller here since this is one section among several.
_STALL_DIFF_CHARS = 4000
_MAX_REVIEW_COMMENTS = 5


class _StatePort(Protocol):
    def get_issue_status(self, issue_number: int) -> str: ...
    def get_all_epic_states(self) -> dict[str, Any]: ...
    def clear_auto_agent_attempts(self, issue: int) -> None: ...
    def reset_issue_attempts(self, issue_number: int) -> None: ...
    def reset_review_attempts(self, issue_number: int) -> None: ...


class _PRPort(Protocol):
    async def find_open_pr_for_branch(
        self, branch: str, *, issue_number: int = 0
    ) -> Any: ...
    async def get_pr_diff_names(self, pr_number: int) -> list[str]: ...
    async def close_pr(self, pr_number: int) -> None: ...
    async def list_branch_commits(
        self, branch: str, *, limit: int = 30
    ) -> list[dict[str, str]]: ...


async def decompose_or_escalate(
    *,
    issue_number: int,
    ctx: PreflightContext,
    config: HydraFlowConfig,
    decomposer: IssueDecomposer | None,
    council: DecompositionCouncil | None,
    state: _StatePort,
    prs: _PRPort,
) -> str:
    """Attempt to decompose *issue_number* before it reaches `human-required`.

    Returns ``"decomposed"`` when the issue was superseded by an epic, OR
    when a closing-keyword commit (``Fixes #N``) for *issue_number* already
    landed — the fix is done, so re-slicing would manufacture children for
    finished work (#11480); either way the caller must NOT add
    `human-required`. Returns ``"human-required"`` when decomposition is not
    wired, the council declines, or the depth cap is already spent (the
    caller applies today's HITL behavior unchanged).

    Idempotent: if a prior — possibly interrupted — tick already decomposed
    this issue, returns ``"decomposed"`` immediately without invoking the
    council or creating a second epic (ADR-0105 §Decision(3)).
    """
    if decomposer is None or council is None:
        # Decompose-to-converge isn't wired for this caller (e.g. a test
        # harness or a deployment that hasn't threaded epic_manager/runner
        # through yet). Graceful degradation to today's behavior — never a
        # hard failure for an optional enhancement.
        return HUMAN_REQUIRED

    if state.get_issue_status(issue_number) == DECOMPOSED:
        logger.info(
            "Issue #%d already decomposed — skipping duplicate decompose attempt",
            issue_number,
        )
        return DECOMPOSED

    if await _landed_closing_ref_present(issue_number, ctx=ctx, config=config, prs=prs):
        logger.info(
            "Issue #%d has a closing-keyword commit already landed — the fix "
            "is done; skipping re-slice instead of manufacturing children "
            "for finished work (#11480)",
            issue_number,
        )
        return DECOMPOSED

    depth = _resolve_depth(issue_number, state)
    if depth >= config.max_decomposition_depth:
        logger.info(
            "Issue #%d already at decomposition depth cap (%d >= %d) — "
            "escalating without invoking the council",
            issue_number,
            depth,
            config.max_decomposition_depth,
        )
        return HUMAN_REQUIRED

    pr_number = await _find_pr_number(issue_number, ctx=ctx, config=config, prs=prs)
    touched_files = await _touched_files(issue_number, pr_number, prs=prs)
    doc_context = gather_decomposition_docs(touched_files, repo_root=config.repo_root)
    stall_context = _build_stall_context(issue_number, ctx)
    task = Task(
        id=issue_number,
        title=f"Issue #{issue_number} ({ctx.sub_label})",
        body=ctx.issue_body,
    )

    epic_number = await _decide_and_create(
        task=task,
        depth=depth,
        stall_context=stall_context,
        doc_context=doc_context,
        council=council,
        decomposer=decomposer,
    )
    if epic_number is None:
        return HUMAN_REQUIRED

    logger.info(
        "Issue #%d decomposed into epic #%d — superseding PR + clearing attempts",
        issue_number,
        epic_number,
    )

    if pr_number:
        try:
            await prs.close_pr(pr_number)
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "Failed to close superseded PR #%d for issue #%d: %s",
                pr_number,
                issue_number,
                exc,
                exc_info=True,
            )

    # create_epic_from_result already closed + mark_issue("decomposed") the
    # source issue; the attempt counters are this terminal's own cleanup so a
    # never-reused issue number doesn't carry stale counts forever.
    state.clear_auto_agent_attempts(issue_number)
    state.reset_issue_attempts(issue_number)
    state.reset_review_attempts(issue_number)

    return DECOMPOSED


async def _decide_and_create(
    *,
    task: Task,
    depth: int,
    stall_context: str,
    doc_context: str,
    council: DecompositionCouncil,
    decomposer: IssueDecomposer,
) -> int | None:
    """Run the council, and on approval create the epic. ``None`` on any
    decline (council or IssueDecomposer's own depth/fanout cap) — the
    caller treats all three the same way (fall through to human-required).
    """
    try:
        result = await council.decide(
            task=task,
            stall_context=stall_context,
            doc_context=doc_context,
            depth=depth,
        )
    except Exception as exc:
        reraise_on_credit_or_bug(exc)
        logger.warning(
            "Decomposition council failed for #%d: %s", task.id, exc, exc_info=True
        )
        return None

    if not result.should_decompose:
        logger.info(
            "Decomposition council declined for #%d (confidence=%r): %s",
            task.id,
            result.confidence,
            result.reasoning,
        )
        return None

    epic_number = await decomposer.create_epic_from_result(
        source_task=task,
        result=result,
        depth=depth,
        stall_context=stall_context,
    )
    if epic_number is None:
        # Declined internally by IssueDecomposer's own depth/fanout cap (a
        # race against another decompose between our pre-check above and
        # this call, or the fanout cap) — same floor as a council decline.
        logger.info(
            "Issue #%d decomposition capped by IssueDecomposer — "
            "falling through to human-required",
            task.id,
        )
    return epic_number


async def _landed_closing_ref_present(
    issue_number: int, *, ctx: PreflightContext, config: HydraFlowConfig, prs: _PRPort
) -> bool:
    """True when a closing-keyword commit (``Fixes #N`` / ``Closes #N`` /
    ``Resolves #N``) for *issue_number* has already landed (#11480) — e.g. a
    fix merged while this issue sat stalled, so decomposing it would
    manufacture children for already-finished work.

    Two evidence channels, either one a hit:
      (a) this tick's already-gathered ``ctx.recent_commits`` (cheap, no
          extra I/O — may miss the fix if its commit doesn't touch a file
          the issue body mentions), and
      (b) the base branch's own recent commit history via
          ``PRPort.list_branch_commits`` (authoritative, but a live read).

    Fails open (``False``) on any scan error: this is an optional pre-check
    ahead of the existing decompose/escalate terminal, which must never be
    blocked by a broken commit-history read.
    """
    try:
        if any(
            issue_number in closing_issue_refs(commit.title)
            for commit in ctx.recent_commits
        ):
            return True
        commits = await prs.list_branch_commits(config.base_branch(), limit=30)
        return any(
            issue_number in closing_issue_refs(commit.get("message", ""))
            for commit in commits
        )
    except Exception as exc:
        reraise_on_credit_or_bug(exc)
        logger.warning(
            "Landed-fix scan failed for #%d: %s", issue_number, exc, exc_info=True
        )
        return False


def _resolve_depth(issue_number: int, state: _StatePort) -> int:
    """Return this issue's decomposition depth.

    Zero for a fresh top-level split. When *issue_number* is itself an
    auto-decomposed child that stalled again, one deeper than the epic that
    created it — spans both the intake-triage and stall-path decomposition
    vectors per ADR-0105 §4, since both write the same
    ``EpicState.decomposition_depth`` field.
    """
    for epic in state.get_all_epic_states().values():
        if issue_number in epic.child_issues:
            return epic.decomposition_depth + 1
    return 0


async def _find_pr_number(
    issue_number: int, *, ctx: PreflightContext, config: HydraFlowConfig, prs: _PRPort
) -> int:
    """Resolve the PR number associated with *issue_number*, or 0 if none."""
    escalation_context = ctx.escalation_context
    if escalation_context is not None and escalation_context.pr_number:
        return escalation_context.pr_number
    try:
        pr = await prs.find_open_pr_for_branch(
            config.branch_for_issue(issue_number), issue_number=issue_number
        )
    except Exception as exc:
        reraise_on_credit_or_bug(exc)
        logger.warning("PR lookup failed for #%d: %s", issue_number, exc, exc_info=True)
        return 0
    # FakeGitHub returns PRInfo(number=0) as an absence sentinel; the real
    # PRManager returns None. Both must be treated as "no open PR".
    if pr is not None and pr.number > 0:
        return pr.number
    return 0


async def _touched_files(
    issue_number: int, pr_number: int, *, prs: _PRPort
) -> list[str]:
    if not pr_number:
        return []
    try:
        return await prs.get_pr_diff_names(pr_number)
    except Exception as exc:
        reraise_on_credit_or_bug(exc)
        logger.warning(
            "Failed to fetch touched files for #%d's PR #%d: %s",
            issue_number,
            pr_number,
            exc,
            exc_info=True,
        )
        return []


def _build_stall_context(issue_number: int, ctx: PreflightContext) -> str:
    """Summarize why *issue_number* stalled for the council's direction pass.

    Feeds ``DecompositionCouncil``'s "why the task stalled" section — the
    diff-so-far (when present) is what lets direction scope a "salvage"
    child that lands the already-working slice instead of discarding it.
    """
    parts: list[str] = []
    escalation_context = ctx.escalation_context
    if escalation_context is not None:
        if escalation_context.origin_phase:
            parts.append(f"Stalled at stage: {escalation_context.origin_phase}")
        if escalation_context.cause:
            parts.append(f"Cause: {escalation_context.cause}")
        if escalation_context.review_comments:
            recent = escalation_context.review_comments[-_MAX_REVIEW_COMMENTS:]
            parts.append("Recent review feedback:\n" + "\n".join(recent))
        if escalation_context.pr_diff:
            parts.append(
                "Diff so far (evidence for a possible salvage child):\n"
                + escalation_context.pr_diff[:_STALL_DIFF_CHARS]
            )
    if ctx.prior_attempts:
        last = ctx.prior_attempts[-1]
        parts.append(
            f"Auto-agent attempt {len(ctx.prior_attempts)} diagnosis "
            f"(status={last.status}): {last.diagnosis}"
        )
    if not parts:
        parts.append(
            f"Issue #{issue_number} exhausted its autonomous retry budget; "
            "no further diagnostic detail is available."
        )
    return "\n\n".join(parts)
