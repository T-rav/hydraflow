"""Plan touchpoint-expander (ADR-0063 W3b).

Dispatched on the FIRST ``PlanReviewer`` blocking-finding failure before
the issue is routed back to plan or escalated. The expander walks
cross-referenced ADRs, recent PR conflict signals, and current wiki
entries for the modules the plan touches, then returns an enriched
``ExpandedTouchpoints`` block. The block is folded into the next
review pass as additional context so the reviewer can re-evaluate the
plan against the proper architectural surface.

Failure mode: this is a read-only subagent call. Any failure (agent
down, malformed JSON, missing fields) returns an empty
``ExpandedTouchpoints`` so the caller falls through to the existing
route-back / HITL escalation path — the expander never blocks
escalation.

See also:
- ``src/assumption_surfacer.py`` — sibling subagent dispatcher (same
  ``AgentLike`` contract, same JSON-parse soft-fail policy).
- ``src/plan_reviewer.py`` — produces the ``PlanReview`` consumed here.
- ADR-0063 §"Implementation strategy — W3" — design rationale.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from exception_classify import reraise_on_credit_or_bug
from models import PlanFindingSeverity, PlanReview
from src.adversarial_agents import AgentLike

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Marker contract
# ---------------------------------------------------------------------------

# The expander agent brackets its structured output with these markers so
# the parser can extract the touchpoints block deterministically. Mirrors
# the ``PLAN_REVIEW_START`` / ``PLAN_REVIEW_END`` shape used by
# ``PlanReviewer`` so the agent operator sees a consistent contract.
TOUCHPOINTS_START = "TOUCHPOINTS_START"
TOUCHPOINTS_END = "TOUCHPOINTS_END"


# Touchpoint kinds we recognize. Anything else collapses to ``other`` so
# malformed agent output doesn't poison the downstream reviewer prompt.
_KNOWN_KINDS: frozenset[str] = frozenset({"adr", "pr", "wiki"})


@dataclass
class Touchpoint:
    """A single architectural touchpoint the expander surfaced.

    ``kind`` is normalized to lowercase at construction; unknown values
    collapse to ``other`` so the reviewer's next-pass prompt stays
    well-formed even on malformed agent output.
    """

    kind: str
    ref: str
    title: str = ""
    why: str = ""

    def __post_init__(self) -> None:
        normalized = self.kind.lower().strip()
        self.kind = normalized if normalized in _KNOWN_KINDS else "other"


@dataclass
class ExpandedTouchpoints:
    """Output of the touchpoint-expander.

    ``touchpoints`` is the parsed list (possibly empty). ``error`` is set
    when the agent or parser soft-failed — callers can log it but should
    still treat the result as a no-op (no touchpoints surfaced means the
    next pass runs without enrichment, same as if the expander never ran).
    """

    touchpoints: list[Touchpoint] = field(default_factory=list)
    duration_seconds: float = 0.0
    error: str | None = None

    def render_context_block(self) -> str:
        """Render the touchpoints as a markdown block for the next reviewer pass.

        Returns an empty string when no touchpoints are present so the
        caller can unconditionally concatenate the block into the next
        review prompt without a guard. The block is wrapped in
        ``EXPANDED_TOUCHPOINTS`` markers so the reviewer agent can find
        the inserted context regardless of surrounding prose.
        """
        if not self.touchpoints:
            return ""
        lines = ["## EXPANDED_TOUCHPOINTS", ""]
        for t in self.touchpoints:
            title = f" — {t.title}" if t.title else ""
            why = f" ({t.why})" if t.why else ""
            lines.append(f"- [{t.kind}] {t.ref}{title}{why}")
        lines.append("")
        lines.append("## END_EXPANDED_TOUCHPOINTS")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = """\
You are the Plan Touchpoint Expander. The HydraFlow plan reviewer
returned blocking findings against a plan. Your job is to surface the
architectural touchpoints the plan should have considered: ADR
cross-references, recent merged PRs that touched the same files (a
conflict-history signal), and current per-repo wiki entries for the
affected modules.

You are a read-only research agent. Do not propose a new plan. Do not
critique the reviewer. Return ONLY the touchpoints the next planner
attempt needs in front of it to satisfy `writing-plans`-shaped success
criteria: concrete, observable, testable.

Output strict JSON between the TOUCHPOINTS_START and TOUCHPOINTS_END
markers, with this shape:
TOUCHPOINTS_START
{
  "touchpoints": [
    {"kind": "adr|pr|wiki",
     "ref": "ADR-NNNN | #PR | path/to/wiki/entry.md",
     "title": "human-readable title",
     "why": "one sentence — why this touchpoint matters for the failed findings"}
  ]
}
TOUCHPOINTS_END

If no relevant touchpoints exist, return an empty "touchpoints" list.
Bound your output to the touchpoints with the highest blast radius —
typically 3-8 entries. Do not pad.
"""


class PlanTouchpointExpander:
    """Read-only subagent that expands ADR/PR/wiki touchpoints for a failed plan review.

    Instantiated with an ``AgentLike`` adapter — same shape as the
    earlier-adversarial pipeline agents (``AssumptionSurfacer``,
    ``SpecJudge``, etc.). The factory wires a real Claude-CLI-backed
    adapter; tests use a JSON-returning stub.
    """

    def __init__(self, agent: AgentLike) -> None:
        self._agent = agent

    async def expand_touchpoints(
        self,
        *,
        original_plan: str,
        reviewer_failure: PlanReview,
    ) -> ExpandedTouchpoints:
        """Run the expander against a failed plan review.

        Returns an ``ExpandedTouchpoints`` carrying the parsed
        touchpoints (possibly empty). Never raises into the caller —
        agent failures soft-fail with ``error`` populated and an empty
        touchpoint list so the existing route-back path remains intact.

        Defensive: if the caller invokes the expander on a review with
        no blocking findings, we return an empty result without burning
        an agent call.
        """
        start = time.monotonic()

        blocking = [
            f
            for f in reviewer_failure.findings
            if f.severity in (PlanFindingSeverity.CRITICAL, PlanFindingSeverity.HIGH)
        ]
        if not blocking:
            logger.debug(
                "plan_touchpoint_expander invoked with no blocking findings — "
                "skipping agent call"
            )
            return ExpandedTouchpoints(duration_seconds=time.monotonic() - start)

        prompt = self._build_prompt(plan=original_plan, findings=blocking)

        try:
            raw = await self._agent.run(_SYSTEM_PROMPT, prompt)
        except Exception as exc:  # noqa: BLE001
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "plan_touchpoint_expander agent raised — soft-failing: %s", exc
            )
            return ExpandedTouchpoints(
                duration_seconds=time.monotonic() - start,
                error=f"agent failure: {exc}",
            )

        touchpoints = self._parse_touchpoints(raw)
        return ExpandedTouchpoints(
            touchpoints=touchpoints,
            duration_seconds=time.monotonic() - start,
        )

    # ------------------------------------------------------------------
    # Pure helpers (testable in isolation)
    # ------------------------------------------------------------------

    @classmethod
    def _build_prompt(
        cls,
        *,
        plan: str,
        findings: list,  # type: ignore[type-arg]
    ) -> str:
        """Build the user-message prompt for the expander agent.

        Filters to blocking severities (critical/high) so the agent's
        context window is spent on the failures that actually drove the
        route-back. Pure function — no I/O.
        """
        blocking = [
            f
            for f in findings
            if f.severity in (PlanFindingSeverity.CRITICAL, PlanFindingSeverity.HIGH)
        ]
        findings_block = (
            "\n".join(
                f"- [{f.severity}] {f.dimension}: {f.description}" for f in blocking
            )
            or "(no blocking findings)"
        )

        return (
            f"## Plan that failed review\n\n"
            f"{plan}\n\n"
            f"## Blocking review findings\n\n"
            f"{findings_block}\n\n"
            f"## Task\n\n"
            f"Identify the architectural touchpoints (ADRs, recent PRs on "
            f"the same files, current wiki entries) the next plan attempt "
            f"must consider to satisfy `writing-plans`-shaped success "
            f"criteria: concrete, observable, testable.\n\n"
            f"Emit your structured output between {TOUCHPOINTS_START} and "
            f"{TOUCHPOINTS_END} markers as specified."
        )

    @classmethod
    def _parse_touchpoints(cls, raw: str) -> list[Touchpoint]:
        """Extract structured touchpoints from the agent's raw output.

        Tolerates the agent emitting a raw JSON object or wrapping the
        JSON in TOUCHPOINTS_START/END markers. Missing required fields
        cause that entry to be skipped; malformed JSON returns an empty
        list (soft-fail).
        """
        # Permit the agent to emit either raw JSON or a marker-wrapped block.
        json_text = raw
        start_idx = raw.find(TOUCHPOINTS_START)
        end_idx = raw.find(TOUCHPOINTS_END)
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_text = raw[start_idx + len(TOUCHPOINTS_START) : end_idx].strip()

        try:
            data = json.loads(json_text)
        except json.JSONDecodeError:
            logger.warning(
                "plan_touchpoint_expander: agent output not parseable as JSON"
            )
            return []

        if not isinstance(data, dict):
            return []
        entries = data.get("touchpoints")
        if not isinstance(entries, list):
            return []

        touchpoints: list[Touchpoint] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            kind = entry.get("kind")
            ref = entry.get("ref")
            if not kind or not ref:
                continue
            touchpoints.append(
                Touchpoint(
                    kind=str(kind),
                    ref=str(ref),
                    title=str(entry.get("title", "")),
                    why=str(entry.get("why", "")),
                )
            )
        return touchpoints


__all__ = [
    "ExpandedTouchpoints",
    "PlanTouchpointExpander",
    "Touchpoint",
    "TOUCHPOINTS_END",
    "TOUCHPOINTS_START",
]
