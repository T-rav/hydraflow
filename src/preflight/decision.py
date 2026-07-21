"""PreflightDecision — pure label-state mapping for AutoAgentPreflightLoop.

Spec §2.2, §2.3, §7. Translates a PreflightResult into label operations
applied via PRPort. Label operations are idempotent (GitHub dedup); comment
deduplication is the caller's responsibility — re-running apply_decision
on the same input WILL post a duplicate comment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol, cast

logger = logging.getLogger("hydraflow.preflight.decision")


@dataclass(frozen=True)
class PreflightResult:
    status: str  # "resolved" | "retry" | "needs_human" | "fatal" | "pr_failed" | "cost_exceeded" | "timeout"
    pr_url: str | None
    diagnosis: str
    cost_usd: float
    wall_clock_s: float
    tokens: int
    # #9821: True when the model had no pricing entry — render "cost
    # unknown", never $0.00 (a $0 line reads as "cheap", hiding spend).
    cost_unknown: bool = False
    prompt_hash: str = ""  # populated from PreflightSpawn for audit traceability
    # Convergence signals (ADR-0084 pillar B): the agent's self-assessed
    # confidence and why it stopped. ``needs_human`` is only honored for a
    # genuine human-only ``blocked_reason`` at high confidence; otherwise the
    # bail is treated as ``retry`` and the loop tries again next cycle.
    confidence: str = "high"  # "high" | "medium" | "low"
    blocked_reason: str = "none"


class _PRPort(Protocol):
    """Subset of PRPort used by apply_decision.

    Method names match the real PRManager / FakeGitHub surface:
    `add_labels` (plural), `remove_label` (singular — call once per label),
    `post_comment` (not `add_comment`). See `src/ports.py` lines 175-198.
    """

    async def add_labels(self, issue_number: int, labels: list[str]) -> None: ...
    async def remove_label(self, issue_number: int, label: str) -> None: ...
    async def post_comment(self, issue_number: int, body: str) -> None: ...
    async def swap_pipeline_labels(self, issue_number: int, new_label: str) -> None: ...


# Status → (labels-to-add, labels-to-remove)
#
# Note: `resolved` removes `human-required` as well as `hitl-escalation` so a
# previously-failed-then-re-submitted issue (operator manually reset state)
# doesn't stay in the human queue after a successful auto-fix.
_LABEL_MAP: dict[str, tuple[list[str], list[str]]] = {
    "resolved": ([], ["hitl-escalation", "human-required"]),
    # `retry` (ADR-0084 B): a recoverable/low-confidence bail. Add nothing and
    # remove nothing — the issue keeps `hitl-escalation` (no `human-required`)
    # so the loop re-attempts next cycle. If the attempt budget is exhausted,
    # the exhaustion branch below escalates it to a human.
    "retry": ([], []),
    "needs_human": (["human-required"], []),
    "fatal": (["human-required", "auto-agent-fatal"], []),
    "pr_failed": (["human-required", "auto-agent-pr-failed"], []),
    "cost_exceeded": (["human-required", "cost-exceeded"], []),
    "timeout": (["human-required", "timeout"], []),
}


async def apply_decision(
    *,
    issue_number: int,
    sub_label: str,
    result: PreflightResult,
    pr_port: _PRPort,
    state: Any,
    max_attempts: int,
    decomposer: Any | None = None,
    council: Any | None = None,
    config: Any | None = None,
    ctx: Any | None = None,
    hitl_widened: bool = False,
    origin_label: str | None = None,
) -> dict[str, Any]:
    """Apply labels + comment for a single attempt's result.

    ADR-0105: when this attempt's label set is about to add `human-required`
    (the needs_human/fatal/pr_failed/cost_exceeded/timeout rows, or the
    exhaustion top-up below), *decomposer*/*council*/*config*/*ctx* — when all
    four are wired — first try `decompose_terminal.decompose_or_escalate`.
    A successful decompose supersedes the whole label/comment step (the
    issue is already closed + `mark_issue("decomposed")` by
    `IssueDecomposer.create_epic_from_result`); a decline or missing wiring
    falls through to today's behavior unchanged.

    #9721 widened intake: *hitl_widened* marks an issue that arrived via the
    widened ``hydraflow-hitl`` poll and is claimed under the autofix label.
    The resolver owns the transition (mirrors ``HITLPhase``):

    - ``resolved`` → swap the claim to *origin_label* (``ready_label[0]`` when
      no origin was recorded), reset ``issue_attempts``, clear
      ``hitl_origin``/``hitl_cause``. No ``human-required``.
    - terminal / exhausted → swap the claim back to ``hitl_label[0]`` (the
      human queue) BEFORE the ``human-required`` add — the swap clears
      ``human-required`` because it rides in ``all_pipeline_labels``.
    - ``retry`` with budget left → keep the claim; the next tick re-attempts.

    ``hitl_widened=False`` keeps today's behavior byte-for-byte.
    """
    # Race-detection: re-read attempts to ensure no concurrent bumper.
    current_attempts = state.get_auto_agent_attempts(issue_number)

    add, remove = _LABEL_MAP.get(result.status, _LABEL_MAP["needs_human"])

    # Spec §3 (state transitions, line 119): a successful resolve also removes
    # the sub-label so the issue doesn't carry an orphaned routing tag in the
    # GitHub UI. The base _LABEL_MAP can't encode this because the sub-label
    # is dynamic per call. Widened issues are exempt: their sub_label is a
    # playbook routing stem derived from hitl_origin, not an issue label.
    if (
        result.status == "resolved"
        and sub_label
        and sub_label != "_default"
        and not hitl_widened
    ):
        remove = list(remove) + [sub_label]

    # Exhaustion check — if this attempt brought us to the cap and it didn't
    # resolve, flag as exhausted on top of the normal needs_human/fatal label
    # set. A `retry` that exhausts its budget must still escalate to a human:
    # its base label map adds no `human-required`, so add it here.
    exhausted = result.status != "resolved" and current_attempts >= max_attempts
    if exhausted:
        add = list(add)
        if "human-required" not in add:
            add.append("human-required")
        if "auto-agent-exhausted" not in add:
            add.append("auto-agent-exhausted")

    decomposed = False
    if (
        "human-required" in add
        and decomposer is not None
        and council is not None
        and config is not None
        and ctx is not None
    ):
        from preflight.decompose_terminal import _PRPort as _DecomposePRPort
        from preflight.decompose_terminal import decompose_or_escalate

        # decision._PRPort and decompose_terminal._PRPort are distinct minimal
        # Protocols (different method subsets); the concrete runtime object is a
        # full PRManager/FakeGitHub that satisfies both, so cast across. Use a
        # non-string cast so ruff counts the import as used (a cast("...") string
        # would get the alias stripped as "unused").
        outcome = await decompose_or_escalate(
            issue_number=issue_number,
            ctx=ctx,
            config=config,
            decomposer=decomposer,
            council=council,
            state=state,
            prs=cast(_DecomposePRPort, pr_port),
        )
        decomposed = outcome == "decomposed"

    if decomposed:
        # The issue was superseded by an epic — decompose_or_escalate /
        # create_epic_from_result already closed it and posted its own
        # comment. Applying human-required-family labels or the normal
        # attempt comment to an already-closed, already-decomposed issue
        # would be stale noise.
        return {
            "issue": issue_number,
            "status": result.status,
            "exhausted": exhausted,
            "added": [],
            "removed": [],
            "decomposed": True,
            "hitl_widened": hitl_widened,
        }

    if hitl_widened:
        hitl_return = config.hitl_label[0] if config is not None else "hydraflow-hitl"
        ready = config.ready_label[0] if config is not None else "hydraflow-ready"
        if result.status == "resolved":
            # Mirror HITLPhase's successful-correction transition: back to the
            # origin stage (or ready when none recorded, so the issue re-enters
            # the pipeline rather than orphaning), attempts reset, origin/cause
            # cleared. The swap drops the autofix claim label.
            await pr_port.swap_pipeline_labels(issue_number, origin_label or ready)
            state.reset_issue_attempts(issue_number)
            state.remove_hitl_origin(issue_number)
            state.remove_hitl_cause(issue_number)
        elif "human-required" in add:
            # Terminal / exhausted: return the claim to the human queue. Must
            # happen BEFORE the add below — swap_pipeline_labels clears
            # human-required (it rides in all_pipeline_labels).
            await pr_port.swap_pipeline_labels(issue_number, hitl_return)
        # A non-exhausted `retry` keeps the autofix claim; the widened poll
        # also covers the autofix label, so the next tick re-attempts.

    if add:
        await pr_port.add_labels(issue_number, add)
    for label in remove:
        await pr_port.remove_label(issue_number, label)

    comment = _format_comment(
        sub_label, result, current_attempts, exhausted, max_attempts
    )
    if comment:
        await pr_port.post_comment(issue_number, comment)

    return {
        "issue": issue_number,
        "status": result.status,
        "exhausted": exhausted,
        "added": add,
        "removed": remove,
        "decomposed": False,
        "hitl_widened": hitl_widened,
    }


def _cost_str(result: PreflightResult) -> str:
    """Render cost for comments — 'cost unknown' beats a lying $0.00 (#9821)."""
    return "cost unknown" if result.cost_unknown else f"${result.cost_usd:.2f}"


def _format_comment(
    sub_label: str,
    result: PreflightResult,
    attempts: int,
    exhausted: bool,
    max_attempts: int,
) -> str:
    if result.status == "resolved":
        pr_link = f" PR: {result.pr_url}" if result.pr_url else ""
        return (
            f"**Auto-Agent resolved this issue** (attempt {attempts}, "
            f"sub-label `{sub_label}`, {_cost_str(result)}, "
            f"{result.wall_clock_s:.0f}s).{pr_link}\n\n"
            f"{result.diagnosis}"
        )
    suffix = (
        f" — **{max_attempts} attempts exhausted, no further auto-agent retries**"
        if exhausted
        else ""
    )
    return (
        f"**Auto-Agent attempt {attempts} → `{result.status}`** "
        f"(sub-label `{sub_label}`, {_cost_str(result)}, "
        f"{result.wall_clock_s:.0f}s){suffix}.\n\n"
        f"**Diagnosis:**\n{result.diagnosis}"
    )
