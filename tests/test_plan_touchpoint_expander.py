"""Tests for plan_touchpoint_expander (ADR-0063 W3b).

The expander is a read-only subagent dispatched on the FIRST PlanReviewer
blocking-finding failure. It walks ADR cross-references, recent PR
conflict signals, and related wiki entries for the modules the plan
touches, then returns an enriched touchpoint list that is folded back
into the next review pass as context.

These are pure-helper tests:

  1. ``_build_prompt`` includes the original plan, the blocking findings,
     and the success-criteria framing.
  2. ``_parse_touchpoints`` extracts a structured ``ExpandedTouchpoints``
     payload from the agent JSON, with soft-fail behavior on malformed
     output.
  3. ``expand_touchpoints`` orchestrates the agent call and returns an
     ``ExpandedTouchpoints`` carrying the parsed payload + duration.

Pattern mirrors ``test_assumption_surfacer.py`` /
``test_spec_judge.py`` — a stub ``AgentLike`` captures the prompt and
returns a canned JSON payload.
"""

from __future__ import annotations

import json

import pytest

from models import PlanFinding, PlanFindingSeverity, PlanReview
from plan_touchpoint_expander import (
    ExpandedTouchpoints,
    PlanTouchpointExpander,
    Touchpoint,
)

# ---------------------------------------------------------------------------
# Stub fixtures
# ---------------------------------------------------------------------------


class _StubAgent:
    """Captures the prompts and returns a canned JSON payload."""

    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.last_system_prompt: str | None = None
        self.last_user_message: str | None = None
        self.calls = 0

    async def run(self, system_prompt: str, user_message: str) -> str:
        self.calls += 1
        self.last_system_prompt = system_prompt
        self.last_user_message = user_message
        return self.payload


def _finding(
    severity: PlanFindingSeverity = PlanFindingSeverity.HIGH,
    dimension: str = "correctness",
    description: str = "missed ADR-0021 cross-ref",
    suggestion: str = "",
) -> PlanFinding:
    return PlanFinding(
        severity=severity,
        dimension=dimension,
        description=description,
        suggestion=suggestion,
    )


def _review(findings: list[PlanFinding]) -> PlanReview:
    return PlanReview(
        issue_number=42,
        plan_version=1,
        success=True,
        findings=findings,
        summary="some blocking findings",
    )


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    def test_includes_plan_text(self) -> None:
        prompt = PlanTouchpointExpander._build_prompt(
            plan="step 1: load config\nstep 2: edit foo.py",
            findings=[_finding()],
        )
        assert "step 1: load config" in prompt
        assert "step 2: edit foo.py" in prompt

    def test_includes_blocking_findings(self) -> None:
        prompt = PlanTouchpointExpander._build_prompt(
            plan="plan body",
            findings=[
                _finding(
                    severity=PlanFindingSeverity.CRITICAL,
                    dimension="convention",
                    description="ignored ADR-0042 base branch rule",
                ),
                _finding(
                    severity=PlanFindingSeverity.HIGH,
                    dimension="test_strategy",
                    description="no MockWorld scenario",
                ),
            ],
        )
        assert "critical" in prompt.lower()
        assert "ADR-0042" in prompt
        assert "MockWorld" in prompt

    def test_filters_to_blocking_severities(self) -> None:
        """The expander should not waste tokens on low/info findings."""
        prompt = PlanTouchpointExpander._build_prompt(
            plan="plan",
            findings=[
                _finding(severity=PlanFindingSeverity.LOW, description="cosmetic nit"),
                _finding(
                    severity=PlanFindingSeverity.HIGH,
                    description="serious gap",
                ),
            ],
        )
        assert "serious gap" in prompt
        assert "cosmetic nit" not in prompt

    def test_includes_writing_plans_success_criteria(self) -> None:
        """Per ADR-0063 W3b: the prompt frames success criteria via
        the writing-plans discipline (concrete, observable, testable)."""
        prompt = PlanTouchpointExpander._build_prompt(
            plan="plan",
            findings=[_finding()],
        )
        assert "writing-plans" in prompt.lower() or "success criteria" in prompt.lower()

    def test_asks_for_adr_pr_wiki_touchpoints(self) -> None:
        prompt = PlanTouchpointExpander._build_prompt(
            plan="plan",
            findings=[_finding()],
        )
        # The three categories ADR-0063 W3b enumerates.
        assert "ADR" in prompt
        assert "PR" in prompt or "pull request" in prompt.lower()
        assert "wiki" in prompt.lower()

    def test_emits_marker_contract(self) -> None:
        prompt = PlanTouchpointExpander._build_prompt(
            plan="plan", findings=[_finding()]
        )
        assert "TOUCHPOINTS_START" in prompt
        assert "TOUCHPOINTS_END" in prompt


# ---------------------------------------------------------------------------
# _parse_touchpoints
# ---------------------------------------------------------------------------


class TestParseTouchpoints:
    def test_parses_well_formed_payload(self) -> None:
        payload = json.dumps(
            {
                "touchpoints": [
                    {
                        "kind": "adr",
                        "ref": "ADR-0021",
                        "title": "Persistence architecture",
                        "why": "plan changes state schema",
                    },
                    {
                        "kind": "pr",
                        "ref": "#8700",
                        "title": "Recent state migration",
                        "why": "merge-conflict signal on state/_route_back.py",
                    },
                    {
                        "kind": "wiki",
                        "ref": "architecture-state-persistence.md",
                        "title": "Pydantic schema evolution",
                        "why": "plan touches StateData",
                    },
                ]
            }
        )
        out = PlanTouchpointExpander._parse_touchpoints(payload)
        assert isinstance(out, list)
        assert len(out) == 3
        assert out[0].kind == "adr"
        assert out[0].ref == "ADR-0021"
        assert out[1].kind == "pr"
        assert out[2].kind == "wiki"

    def test_malformed_json_returns_empty(self) -> None:
        out = PlanTouchpointExpander._parse_touchpoints("not json at all")
        assert out == []

    def test_missing_touchpoints_key_returns_empty(self) -> None:
        out = PlanTouchpointExpander._parse_touchpoints(json.dumps({"foo": "bar"}))
        assert out == []

    def test_skips_entries_missing_required_fields(self) -> None:
        payload = json.dumps(
            {
                "touchpoints": [
                    {"kind": "adr"},  # missing ref
                    {
                        "kind": "wiki",
                        "ref": "patterns.md",
                        "title": "OK",
                        "why": "fine",
                    },
                    {"ref": "ADR-0001"},  # missing kind
                ]
            }
        )
        out = PlanTouchpointExpander._parse_touchpoints(payload)
        assert len(out) == 1
        assert out[0].ref == "patterns.md"

    def test_unknown_kind_normalized_to_other(self) -> None:
        payload = json.dumps(
            {
                "touchpoints": [
                    {"kind": "weird", "ref": "X", "title": "T", "why": "w"},
                ]
            }
        )
        out = PlanTouchpointExpander._parse_touchpoints(payload)
        assert len(out) == 1
        assert out[0].kind == "other"


# ---------------------------------------------------------------------------
# expand_touchpoints (orchestration)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExpandTouchpoints:
    async def test_returns_parsed_touchpoints(self) -> None:
        payload = json.dumps(
            {
                "touchpoints": [
                    {
                        "kind": "adr",
                        "ref": "ADR-0042",
                        "title": "Two-tier branch",
                        "why": "PR base branch",
                    },
                ]
            }
        )
        agent = _StubAgent(payload)
        expander = PlanTouchpointExpander(agent=agent)

        out = await expander.expand_touchpoints(
            original_plan="some plan",
            reviewer_failure=_review([_finding()]),
        )

        assert isinstance(out, ExpandedTouchpoints)
        assert len(out.touchpoints) == 1
        assert out.touchpoints[0].ref == "ADR-0042"
        assert agent.calls == 1

    async def test_no_blocking_findings_returns_empty(self) -> None:
        """If the caller invokes the expander on a clean review (defensive),
        we don't burn an agent call — return empty."""
        agent = _StubAgent(payload=json.dumps({"touchpoints": []}))
        expander = PlanTouchpointExpander(agent=agent)

        out = await expander.expand_touchpoints(
            original_plan="plan",
            reviewer_failure=_review([_finding(severity=PlanFindingSeverity.LOW)]),
        )

        assert out.touchpoints == []
        assert agent.calls == 0

    async def test_agent_failure_returns_empty_soft_fail(self) -> None:
        """Agent raising should not crash the caller — soft-fail."""

        class _RaisingAgent:
            async def run(self, system_prompt: str, user_message: str) -> str:
                raise RuntimeError("agent down")

        expander = PlanTouchpointExpander(agent=_RaisingAgent())

        out = await expander.expand_touchpoints(
            original_plan="plan",
            reviewer_failure=_review([_finding()]),
        )

        assert isinstance(out, ExpandedTouchpoints)
        assert out.touchpoints == []
        assert out.error is not None

    async def test_renders_context_block(self) -> None:
        """The result should expose a rendered context block usable by
        the next reviewer pass."""
        payload = json.dumps(
            {
                "touchpoints": [
                    {
                        "kind": "adr",
                        "ref": "ADR-0001",
                        "title": "Async loops",
                        "why": "concurrency model",
                    },
                    {
                        "kind": "wiki",
                        "ref": "gotchas.md",
                        "title": "Worktree rules",
                        "why": "plan creates branches",
                    },
                ]
            }
        )
        expander = PlanTouchpointExpander(agent=_StubAgent(payload))

        out = await expander.expand_touchpoints(
            original_plan="plan",
            reviewer_failure=_review([_finding()]),
        )

        block = out.render_context_block()
        assert "ADR-0001" in block
        assert "gotchas.md" in block
        # Marker shape so the reviewer can recognize the inserted block.
        assert "EXPANDED_TOUCHPOINTS" in block


class TestTouchpoint:
    def test_normalizes_kind_case(self) -> None:
        t = Touchpoint(kind="ADR", ref="ADR-0001", title="t", why="w")
        assert t.kind == "adr"


class TestExpandedTouchpoints:
    def test_empty_render_returns_empty_string(self) -> None:
        out = ExpandedTouchpoints()
        assert out.render_context_block() == ""
