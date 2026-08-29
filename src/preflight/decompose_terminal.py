"""decompose_or_escalate — the auto-agent's decompose-before-HITL terminal.

ADR-0105 §Decision(1): at both places the auto-agent applies `human-required`
(`auto_agent_preflight_loop.py`'s attempt-cap pre-check, `preflight/decision.py`'s
`apply_decision` exhaustion + `_LABEL_MAP` needs_human/fatal path), this module
is called FIRST. Only when it declines (returns ``"human-required"``) does the
caller apply today's ADR-0084 behavior unchanged; when it decomposes, the
stuck issue is superseded by an epic + children and `human-required` is never
added.

This is the sole place `IssueDecomposer` and `DecompositionEnsemble` are wired
together for the stall path (both are otherwise only exercised directly by
unit tests). Depth is resolved from any existing epic that already claims
this issue as a child (`EpicState.decomposition_depth + 1`) so a
re-decomposed auto-child's lineage is correctly bounded by
`config.max_decomposition_depth` — the same counter intake-triage decomposition
increments (ADR-0105 §4).

#11480: the attempt cap trips on attempt *count*, never on attempt *outcome*,
so a final attempt that produced a landing PR still arrives here on the next
tick. Before the ensemble is ever asked (and before any epic is created), this
module now looks for evidence that the work is already done —
:func:`_find_landed_fix` — and returns a third outcome, ``already-satisfied``,
which neither decomposes nor pages a human. Both call sites
(`auto_agent_preflight_loop`'s attempt-cap pre-check and
`preflight/decision.py`'s `apply_decision`) understand it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from decomposition_docs import gather_decomposition_docs
from exception_classify import reraise_on_credit_or_bug

# One closing-keyword parser for both evidence sources — PR title/body and
# commit messages. ``escape.attribution.extract_fixes_refs`` is the same
# grammar over the same text; reusing this one keeps the terminal from
# straddling two packages for a single predicate.
from false_close import closing_issue_refs
from models import Task

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from decomposition_ensemble import DecompositionEnsemble
    from issue_decomposer import IssueDecomposer
    from preflight.context import PreflightContext

logger = logging.getLogger("hydraflow.preflight.decompose_terminal")

DECOMPOSED = "decomposed"
HUMAN_REQUIRED = "human-required"
ALREADY_SATISFIED = "already-satisfied"

# Bounds on how much of the stall evidence goes into the ensemble prompt —
# mirrors decomposition_ensemble.py's own task-body truncation (5000 chars);
# kept smaller here since this is one section among several.
_STALL_DIFF_CHARS = 4000
_MAX_REVIEW_COMMENTS = 5

# GitHub issue states that mean "no longer open work". Only these exact
# values trip the already-satisfied skip: both `PRManager.get_issue_state`
# and `FakeGitHub.get_issue_state` fail-closed with ``"UNKNOWN"`` on an
# unreadable/unseen issue, and an unknown state must never suppress a real
# decomposition (liveness beats a guess).
_CLOSED_ISSUE_STATES = frozenset({"CLOSED", "COMPLETED", "NOT_PLANNED"})

# ``gh pr checks --json state`` values that mean this PR's CI is *failing*
# (subset of contracts.shapes._GhCheckState's terminal conclusions). Pending
# states — QUEUED/IN_PROGRESS/PENDING/WAITING — are deliberately absent: a PR
# whose CI is still running is in flight, not stalled. That distinction is
# what makes the #11427 shape (PR opened 13:10, re-sliced 13:38, merged
# 14:06) detectable at the moment the terminal runs.
_FAILING_CI_STATES = frozenset(
    {
        "FAILURE",
        "CANCELLED",
        "TIMED_OUT",
        "ACTION_REQUIRED",
        "STALE",
        "STARTUP_FAILURE",
    }
)

# How far back to scan the integration branch for a commit that already
# declares a fix for the issue. GitHub caps ``per_page`` at 100, and the
# window has to cover a busy factory day — #11427's fix landed at 07:08 and
# the re-slice fired at 13:38.
_BASE_COMMIT_SCAN_LIMIT = 100

# Idempotency marker for the skip comment: the issue stays in the pipeline,
# so every later tick re-enters this path and must not re-comment.
_ALREADY_SATISFIED_MARKER = "<!-- hydraflow:already-satisfied -->"


@dataclass(frozen=True)
class _LandedFix:
    """Evidence that *issue_number*'s fix is already done or in flight.

    One field on purpose: the evidence is written for the issue comment and
    the log line, and every signal names its own source (PR number, commit
    subject, or issue state) inside it.
    """

    evidence: str


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
    async def get_issue_state(self, issue_number: int) -> str: ...
    async def get_pr_title_and_body(self, pr_number: int) -> tuple[str, str]: ...
    async def get_pr_checks(self, pr_number: int) -> list[dict[str, str]]: ...
    async def get_pr_reviews(self, pr_number: int) -> list[dict[str, str]]: ...
    async def get_pr_mergeable(self, pr_number: int) -> bool | None: ...
    async def list_branch_commits(
        self, branch: str, *, limit: int = 30
    ) -> list[dict[str, str]]: ...
    async def post_comment(self, issue_number: int, body: str) -> None: ...


async def decompose_or_escalate(
    *,
    issue_number: int,
    ctx: PreflightContext,
    config: HydraFlowConfig,
    decomposer: IssueDecomposer | None,
    ensemble: DecompositionEnsemble | None,
    state: _StatePort,
    prs: _PRPort,
) -> str:
    """Attempt to decompose *issue_number* before it reaches `human-required`.

    Returns ``"decomposed"`` when the issue was superseded by an epic (the
    caller must NOT add `human-required`), ``"already-satisfied"`` when a fix
    for the issue has already landed or is in flight (the caller must neither
    decompose nor page a human — the issue stays in the pipeline and closes
    with its fix), or ``"human-required"`` when decomposition is not wired,
    the ensemble declines, or the depth cap is already spent (the caller
    applies today's HITL behavior unchanged).

    Idempotent: if a prior — possibly interrupted — tick already decomposed
    this issue, returns ``"decomposed"`` immediately without invoking the
    ensemble or creating a second epic (ADR-0105 §Decision(3)).
    """
    if decomposer is None or ensemble is None:
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

    # #11480: the work-already-done gate. Runs BEFORE the depth cap (a landed
    # fix must not page a human either) and before the ensemble, so a
    # spuriously-stalled issue costs neither an LLM call nor a planning cycle.
    landed = await _find_landed_fix(issue_number, config=config, prs=prs)
    if landed is not None:
        logger.info(
            "Issue #%d already satisfied (%s) — skipping decomposition",
            issue_number,
            landed.evidence,
        )
        await _announce_already_satisfied(issue_number, landed, ctx=ctx, prs=prs)
        return ALREADY_SATISFIED

    depth = _resolve_depth(issue_number, state)
    if depth >= config.max_decomposition_depth:
        logger.info(
            "Issue #%d already at decomposition depth cap (%d >= %d) — "
            "escalating without invoking the ensemble",
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
        ensemble=ensemble,
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
        await _supersede_pr(pr_number, issue_number, prs=prs)

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
    ensemble: DecompositionEnsemble,
    decomposer: IssueDecomposer,
) -> int | None:
    """Run the ensemble, and on approval create the epic. ``None`` on any
    decline (ensemble or IssueDecomposer's own depth/fanout cap) — the
    caller treats all three the same way (fall through to human-required).
    """
    try:
        result = await ensemble.decide(
            task=task,
            stall_context=stall_context,
            doc_context=doc_context,
            depth=depth,
        )
    except Exception as exc:
        reraise_on_credit_or_bug(exc)
        logger.warning(
            "Decomposition ensemble failed for #%d: %s", task.id, exc, exc_info=True
        )
        return None

    if not result.should_decompose:
        logger.info(
            "Decomposition ensemble declined for #%d (confidence=%r): %s",
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
        # this call, or the fanout cap) — same floor as a ensemble decline.
        logger.info(
            "Issue #%d decomposition capped by IssueDecomposer — "
            "falling through to human-required",
            task.id,
        )
    return epic_number


async def _supersede_pr(pr_number: int, issue_number: int, *, prs: _PRPort) -> None:
    """Close *pr_number* as superseded by the epic — unless it is a landing fix.

    Defence in depth (#11480). The already-satisfied gate reads the two agent
    branches; ``pr_number`` can also come straight from
    ``ctx.escalation_context``, which bypasses that resolution entirely.
    Closing a complete, green fix is unrecoverable work loss, so this
    re-checks the exact PR it is about to close.
    """
    if await _is_landing_fix_pr(pr_number, issue_number, prs=prs):
        logger.warning(
            "Not closing PR #%d for decomposed issue #%d — it declares a fix "
            "for the issue and is still viable (#11480)",
            pr_number,
            issue_number,
        )
        return
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
    """Resolve the PR number associated with *issue_number*, or 0 if none.

    Tries BOTH branch names an issue's work can live on
    (``config.agent_branches_for_issue``), manual-first per that helper's
    documented precedence. Resolving only ``agent/issue-{N}`` is the #11281/
    #11282 defect class: the auto-agent mints its own
    ``agent/auto-agent-{N}`` branch, so a manual-only lookup is blind to the
    auto-agent's own PR — which is exactly why #11427's PR was never seen by
    this terminal (no salvage diff for the ensemble, no supersede close).
    """
    escalation_context = ctx.escalation_context
    if escalation_context is not None and escalation_context.pr_number:
        return escalation_context.pr_number
    for branch in config.agent_branches_for_issue(issue_number):
        pr = await _open_pr_on_branch(branch, issue_number, prs=prs)
        if pr is not None:
            return int(pr.number)
    return 0


async def _open_pr_on_branch(branch: str, issue_number: int, *, prs: _PRPort) -> Any:
    """Return the open PR object on *branch*, or ``None`` when there is none.

    FakeGitHub returns ``PRInfo(number=0)`` as an absence sentinel; the real
    PRManager returns ``None``. Both must read as "no open PR".
    """
    try:
        pr = await prs.find_open_pr_for_branch(branch, issue_number=issue_number)
    except Exception as exc:
        reraise_on_credit_or_bug(exc)
        logger.warning(
            "PR lookup failed for #%d on %s: %s",
            issue_number,
            branch,
            exc,
            exc_info=True,
        )
        return None
    if pr is None:
        return None
    number = getattr(pr, "number", 0)
    return pr if isinstance(number, int) and number > 0 else None


async def _find_landed_fix(
    issue_number: int, *, config: HydraFlowConfig, prs: _PRPort
) -> _LandedFix | None:
    """Return evidence that *issue_number*'s fix already landed, else ``None``.

    Three signals, cheapest first (#11480):

    (a) GitHub says the issue is no longer open — it closed under us, either
        mid-tick or via a closing keyword on a merge we haven't observed.
    (b) An open, non-draft PR on either agent branch that declares a closing
        keyword for this issue and whose CI is not failing — the fix is in
        flight and will land on its own (#11427's exact shape).
    (c) A commit already on the integration branch whose message declares a
        closing keyword for this issue — the merged-but-not-yet-closed and
        reopened-issue cases.

    Every read fails OPEN (returns ``None``, i.e. "no evidence"): an
    unreadable signal must never suppress a genuine decomposition, or a
    flaky ``gh`` call would silently park stalled issues forever.
    """
    issue_state = await _issue_state(issue_number, prs=prs)
    if issue_state in _CLOSED_ISSUE_STATES:
        return _LandedFix(
            evidence=f"the issue is already closed on GitHub (state `{issue_state}`)"
        )

    for branch in config.agent_branches_for_issue(issue_number):
        pr = await _open_pr_on_branch(branch, issue_number, prs=prs)
        if pr is None or bool(getattr(pr, "draft", False)):
            continue
        pr_number = int(pr.number)
        if not await _is_landing_fix_pr(pr_number, issue_number, prs=prs):
            continue
        return _LandedFix(
            evidence=(
                f"open PR #{pr_number} on `{branch}` declares a fix for this "
                "issue and its CI is not failing"
            )
        )

    return await _find_landed_commit(issue_number, config=config, prs=prs)


async def _issue_state(issue_number: int, *, prs: _PRPort) -> str:
    """Return the GitHub state of *issue_number*, or ``""`` when unreadable."""
    try:
        issue_state = await prs.get_issue_state(issue_number)
    except Exception as exc:
        reraise_on_credit_or_bug(exc)
        logger.warning(
            "Issue-state lookup failed for #%d: %s", issue_number, exc, exc_info=True
        )
        return ""
    # An unconfigured test double can return a non-str; treat it as unreadable
    # rather than letting a repr trip (or vacuously pass) the closed check.
    return issue_state.upper() if isinstance(issue_state, str) else ""


async def _is_landing_fix_pr(
    pr_number: int, issue_number: int, *, prs: _PRPort
) -> bool:
    """True when *pr_number* is a viable fix for *issue_number*.

    Viable means all four: its title/body declares a GitHub closing keyword
    for the issue, GitHub does not report it as conflicting, its CI reports
    at least one check with none of them failing, and no reviewer has
    requested changes on it.

    Every clause fails toward "not viable", because that is today's
    behavior — this predicate both suppresses decomposition and vetoes the
    supersede close, so a guess here parks an issue nobody is looking at.
    Requiring a check to *exist* is the same principle: an empty check list
    is absence of evidence, not evidence of health. The
    changes-requested clause is what keeps a review-rejected PR (green CI,
    genuinely stuck) on today's escalate-or-decompose path.
    """
    title, body = await _pr_title_and_body(pr_number, prs=prs)
    if issue_number not in closing_issue_refs(f"{title}\n{body}"):
        return False
    try:
        mergeable = await prs.get_pr_mergeable(pr_number)
    except Exception as exc:
        reraise_on_credit_or_bug(exc)
        logger.warning(
            "Mergeable lookup failed for PR #%d: %s", pr_number, exc, exc_info=True
        )
        return False
    if mergeable is False:
        return False
    if await _has_changes_requested(pr_number, prs=prs):
        return False
    return await _ci_is_not_failing(pr_number, prs=prs)


async def _has_changes_requested(pr_number: int, *, prs: _PRPort) -> bool:
    """True when any review on *pr_number* requested changes.

    GitHub keeps superseded reviews in the list, so a PR whose feedback was
    already addressed still reads as changes-requested here. That bias is
    deliberate: it can only send an issue down today's path, never park it.
    An unreadable review list reads as "changes requested" for the same
    reason.
    """
    try:
        reviews = await prs.get_pr_reviews(pr_number)
    except Exception as exc:
        reraise_on_credit_or_bug(exc)
        logger.warning(
            "Review lookup failed for PR #%d: %s", pr_number, exc, exc_info=True
        )
        return True
    if not isinstance(reviews, list):
        return True
    return any(
        isinstance(r, dict) and str(r.get("state", "")).upper() == "CHANGES_REQUESTED"
        for r in reviews
    )


async def _pr_title_and_body(pr_number: int, *, prs: _PRPort) -> tuple[str, str]:
    """Return ``(title, body)`` for *pr_number*, or ``("", "")`` when unreadable."""
    try:
        result = await prs.get_pr_title_and_body(pr_number)
    except Exception as exc:
        reraise_on_credit_or_bug(exc)
        logger.warning(
            "Title/body lookup failed for PR #%d: %s", pr_number, exc, exc_info=True
        )
        return ("", "")
    # Shape-tolerant: an unconfigured double returns a MagicMock, not a
    # 2-tuple of str — that reads as "unreadable", never as a match.
    if isinstance(result, tuple) and len(result) == 2:
        title, body = result
        if isinstance(title, str) and isinstance(body, str):
            return (title, body)
    return ("", "")


async def _ci_is_not_failing(pr_number: int, *, prs: _PRPort) -> bool:
    """True when *pr_number* has CI checks and none of them are failing.

    Pending checks count as not-failing: a PR whose CI is still running is in
    flight, not stalled. Mirrors ``AutoAgentPreflightLoop._is_resolved_by_open_pr``'s
    shape-tolerance — an unconfigured double returning a non-list reads as
    "no evidence".
    """
    try:
        checks = await prs.get_pr_checks(pr_number)
    except Exception as exc:
        reraise_on_credit_or_bug(exc)
        logger.warning(
            "CI-check lookup failed for PR #%d: %s", pr_number, exc, exc_info=True
        )
        return False
    if not isinstance(checks, list) or not checks:
        return False
    return not any(
        isinstance(c, dict) and str(c.get("state", "")).upper() in _FAILING_CI_STATES
        for c in checks
    )


async def _find_landed_commit(
    issue_number: int, *, config: HydraFlowConfig, prs: _PRPort
) -> _LandedFix | None:
    """Return evidence of a commit on the integration branch that fixes *issue_number*."""
    base = config.base_branch()
    try:
        commits = await prs.list_branch_commits(base, limit=_BASE_COMMIT_SCAN_LIMIT)
    except Exception as exc:
        reraise_on_credit_or_bug(exc)
        logger.warning(
            "Commit scan of %s failed for #%d: %s",
            base,
            issue_number,
            exc,
            exc_info=True,
        )
        return None
    if not isinstance(commits, list):
        return None
    for commit in commits:
        if not isinstance(commit, dict):
            continue
        message = str(commit.get("message", ""))
        if issue_number not in closing_issue_refs(message):
            continue
        subject = message.splitlines()[0] if message else ""
        return _LandedFix(
            evidence=f"commit already on `{base}` declares the fix: {subject!r}"
        )
    return None


async def _announce_already_satisfied(
    issue_number: int, landed: _LandedFix, *, ctx: PreflightContext, prs: _PRPort
) -> None:
    """Post the skip evidence to the issue — at most once.

    The issue stays in the pipeline with its attempt counters at the cap, so
    every later tick re-enters this path; without the marker check that would
    be one comment per tick, forever.
    """
    for comment in ctx.issue_comments or []:
        if _ALREADY_SATISFIED_MARKER in str(getattr(comment, "body", "")):
            return
    body = (
        f"{_ALREADY_SATISFIED_MARKER}\n"
        "**Re-slice skipped — a fix for this issue has already landed.**\n\n"
        f"Evidence: {landed.evidence}.\n\n"
        "The stall terminal did not decompose this issue into re-slice "
        "children and did not escalate it to a human; it stays in the "
        "pipeline and closes with its fix (#11480)."
    )
    try:
        await prs.post_comment(issue_number, body)
    except Exception as exc:
        reraise_on_credit_or_bug(exc)
        logger.warning(
            "Failed to post already-satisfied comment on #%d: %s",
            issue_number,
            exc,
            exc_info=True,
        )


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
    """Summarize why *issue_number* stalled for the ensemble's direction pass.

    Feeds ``DecompositionEnsemble``'s "why the task stalled" section — the
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
