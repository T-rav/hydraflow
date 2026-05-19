"""Tests for the shape phase — product direction selection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from config import HydraFlowConfig
from expert_council import CouncilResult, CouncilVote
from models import ShapeConversation, Task
from shape_phase import _SHAPE_OPTIONS_MARKER, ShapePhase


@pytest.fixture
def config() -> HydraFlowConfig:
    return HydraFlowConfig(repo="test/repo")


@pytest.fixture
def deps(config: HydraFlowConfig) -> dict:
    """Shared dependencies for ShapePhase."""
    import asyncio

    return {
        "config": config,
        "state": MagicMock(),
        "store": MagicMock(),
        "prs": AsyncMock(),
        "event_bus": AsyncMock(),
        "stop_event": asyncio.Event(),
    }


@pytest.fixture
def phase(deps: dict) -> ShapePhase:
    return ShapePhase(**deps)


@pytest.fixture
def sample_task() -> Task:
    return Task(
        id=42,
        title="Build a better Calendly",
        body="Vague idea",
        labels=["hydraflow-shape"],
    )


class TestShapePhaseGenerate:
    @pytest.mark.asyncio
    async def test_generate_options_posts_comment(
        self, phase: ShapePhase, sample_task: Task, deps: dict
    ) -> None:
        """Shape posts direction options as a comment."""
        # No existing comments with options marker
        deps["store"].enrich_with_comments = AsyncMock(
            return_value=sample_task.model_copy(update={"comments": []})
        )
        await phase._shape_single(sample_task)

        deps["prs"].post_comment.assert_awaited_once()
        comment = deps["prs"].post_comment.call_args[0][1]
        assert _SHAPE_OPTIONS_MARKER in comment
        assert "Direction A" in comment

    @pytest.mark.asyncio
    async def test_generate_options_re_enqueues(
        self, phase: ShapePhase, sample_task: Task, deps: dict
    ) -> None:
        """After posting options, issue is re-enqueued for polling."""
        deps["store"].enrich_with_comments = AsyncMock(
            return_value=sample_task.model_copy(update={"comments": []})
        )
        await phase._shape_single(sample_task)

        # Should re-enqueue to shape for the polling cycle
        deps["store"].enqueue_transition.assert_called_with(sample_task, "shape")


class TestShapePhaseSelection:
    @pytest.mark.asyncio
    async def test_detects_direction_selection(
        self, phase: ShapePhase, sample_task: Task, deps: dict
    ) -> None:
        """Shape detects a direction selection in comments."""
        comments = [
            f"{_SHAPE_OPTIONS_MARKER} for #42\n\n### Direction A: ...",
            "Direction B — but scope it to MVP only",
        ]
        deps["store"].enrich_with_comments = AsyncMock(
            return_value=sample_task.model_copy(update={"comments": comments})
        )
        result = await phase._shape_single(sample_task)

        assert result == 1
        deps["store"].enqueue_transition.assert_called_once_with(sample_task, "plan")
        deps["prs"].transition.assert_awaited_once_with(42, "plan")

    @pytest.mark.asyncio
    async def test_no_selection_re_enqueues(
        self, phase: ShapePhase, sample_task: Task, deps: dict
    ) -> None:
        """When no selection is found, issue is re-enqueued."""
        comments = [
            f"{_SHAPE_OPTIONS_MARKER} for #42\n\n### Direction A: ...",
            "Hmm, interesting options. Let me think about it.",
        ]
        deps["store"].enrich_with_comments = AsyncMock(
            return_value=sample_task.model_copy(update={"comments": comments})
        )
        result = await phase._shape_single(sample_task)

        assert result == 0
        deps["store"].enqueue_transition.assert_called_once_with(sample_task, "shape")

    @pytest.mark.asyncio
    async def test_selection_increments_counter(
        self, phase: ShapePhase, sample_task: Task, deps: dict
    ) -> None:
        """Selection increments the 'shaped' session counter."""
        comments = [
            f"{_SHAPE_OPTIONS_MARKER} for #42\n\n### Direction A: ...",
            "Direction A",
        ]
        deps["store"].enrich_with_comments = AsyncMock(
            return_value=sample_task.model_copy(update={"comments": comments})
        )
        await phase._shape_single(sample_task)

        deps["state"].increment_session_counter.assert_called_once_with("shaped")


class TestSelectionParsing:
    def test_finds_direction_a(self, phase: ShapePhase) -> None:
        comments = [f"{_SHAPE_OPTIONS_MARKER} for #42", "Direction A"]
        assert phase._find_selection(comments) == "A"

    def test_finds_direction_b_case_insensitive(self, phase: ShapePhase) -> None:
        comments = [f"{_SHAPE_OPTIONS_MARKER} for #42", "direction b please"]
        assert phase._find_selection(comments) == "B"

    def test_finds_option_c(self, phase: ShapePhase) -> None:
        comments = [f"{_SHAPE_OPTIONS_MARKER} for #42", "Option C — but scoped down"]
        assert phase._find_selection(comments) == "C"

    def test_ignores_comments_before_options(self, phase: ShapePhase) -> None:
        comments = ["Direction A", f"{_SHAPE_OPTIONS_MARKER} for #42"]
        # "Direction A" appears before the marker, should not be found
        assert phase._find_selection(comments) is None

    def test_returns_none_when_no_selection(self, phase: ShapePhase) -> None:
        comments = [f"{_SHAPE_OPTIONS_MARKER} for #42", "Still thinking..."]
        assert phase._find_selection(comments) is None

    def test_returns_none_with_no_options_marker(self, phase: ShapePhase) -> None:
        comments = ["Just a regular comment", "Direction A"]
        assert phase._find_selection(comments) is None


class TestFormatOptions:
    def test_format_includes_marker(self, phase: ShapePhase, sample_task: Task) -> None:
        from models import ProductDirection, ShapeResult

        result = ShapeResult(
            issue_number=42,
            directions=[
                ProductDirection(
                    name="Simple",
                    approach="Keep it simple",
                    tradeoffs="Less features",
                    effort="Low",
                    risk="Low",
                ),
                ProductDirection(
                    name="Complex",
                    approach="Full featured",
                    tradeoffs="More work",
                    effort="High",
                    risk="Medium",
                    differentiator="Strong",
                ),
            ],
            recommendation="Go with A for MVP",
        )
        formatted = phase._format_options(sample_task, result)

        assert _SHAPE_OPTIONS_MARKER in formatted
        assert "Direction A: Simple" in formatted
        assert "Direction B: Complex" in formatted
        assert "**Differentiator:** Strong" in formatted
        assert "Go with A for MVP" in formatted
        assert "Reply with your selection" in formatted


# ---------------------------------------------------------------------------
# ADR-0063 W4 — council round-3 with diversified personas
# ---------------------------------------------------------------------------


def _make_split_result() -> CouncilResult:
    """Three-way split council result (no consensus)."""
    return CouncilResult(
        [
            CouncilVote("User Advocate", "A", "user reasoning", 7),
            CouncilVote("Technical Lead", "B", "tech reasoning", 7),
            CouncilVote("Product Strategist", "C", "strategy reasoning", 6),
        ]
    )


def _make_consensus_result(direction: str = "B") -> CouncilResult:
    """2/3 supermajority on *direction*."""
    return CouncilResult(
        [
            CouncilVote("Dissenter", direction, "less bad than alternatives", 8),
            CouncilVote("Consensus-Seeker", direction, "broadest acceptance", 7),
            CouncilVote("Regret-in-6-Months", "A", "regret reasoning", 6),
        ]
    )


class TestCouncilVoteRoundThree:
    """Round 3 (W4) activates only when rounds 1 + 2 split, then either
    converges (auto-select) or escalates (returns None)."""

    @pytest.fixture
    def conv(self) -> ShapeConversation:
        return ShapeConversation(
            issue_number=42, started_at="2026-05-19T00:00:00+00:00"
        )

    def _wire_council(
        self,
        phase: ShapePhase,
        round_results: list[CouncilResult],
        diversified_result: CouncilResult | None = None,
    ) -> MagicMock:
        """Wire a mock ExpertCouncil onto *phase*.

        ``round_results`` supplies the standard-panel ``vote`` returns in
        order (round 1, round 2). ``diversified_result`` supplies the
        ``vote_diversified`` return for round 3 (None means round 3 is
        not expected to be called).
        """
        council = MagicMock()
        council.vote = AsyncMock(side_effect=round_results)
        council.mediate = AsyncMock(return_value="mediation synthesis text")
        council.vote_diversified = AsyncMock(return_value=diversified_result)
        phase._council = council
        return council

    @pytest.mark.asyncio
    async def test_round_3_runs_after_two_splits_and_converges(
        self,
        phase: ShapePhase,
        sample_task: Task,
        conv: ShapeConversation,
        deps: dict,
    ) -> None:
        """Two split rounds followed by a converging diversified-panel vote
        produces consensus and returns 1 (issue transitioned to plan).

        This is the W4 happy path: standard panel deadlocks twice, the
        diversified personas break the tie, no human needed.
        """
        diversified = _make_consensus_result("B")
        council = self._wire_council(
            phase,
            round_results=[_make_split_result(), _make_split_result()],
            diversified_result=diversified,
        )

        result = await phase._run_council_vote(sample_task, conv, "directions text")

        assert result == 1
        # Standard panel called twice (rounds 1 + 2)
        assert council.vote.await_count == 2
        # Mediation runs before round 2
        council.mediate.assert_awaited_once()
        # Diversified panel runs exactly once for round 3
        council.vote_diversified.assert_awaited_once()
        # The round-3 prompt includes the prior split for context
        prompt_arg = council.vote_diversified.await_args.args[1]
        assert "Prior Council Vote (Round 2)" in prompt_arg

    @pytest.mark.asyncio
    async def test_round_3_split_escalates_to_human(
        self,
        phase: ShapePhase,
        sample_task: Task,
        conv: ShapeConversation,
        deps: dict,
    ) -> None:
        """If round 3 also splits, ``_run_council_vote`` returns None so the
        caller can fall through to the existing human-escalation path."""
        # All three rounds split. Build the diversified split with names
        # matching the round-3 panel so the format_summary debug output
        # accurately reflects what happened in production.
        diversified_split = CouncilResult(
            [
                CouncilVote("Dissenter", "A", "argues against B", 7),
                CouncilVote("Consensus-Seeker", "B", "broadest fit", 6),
                CouncilVote("Regret-in-6-Months", "C", "least regret", 6),
            ]
        )
        council = self._wire_council(
            phase,
            round_results=[_make_split_result(), _make_split_result()],
            diversified_result=diversified_split,
        )

        result = await phase._run_council_vote(sample_task, conv, "directions text")

        assert result is None
        assert council.vote.await_count == 2
        council.vote_diversified.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_round_1_consensus_skips_round_3(
        self,
        phase: ShapePhase,
        sample_task: Task,
        conv: ShapeConversation,
        deps: dict,
    ) -> None:
        """W4 must activate ONLY on a split after round 2. If round 1 reaches
        consensus, neither the mediator nor the diversified panel runs."""
        consensus = CouncilResult(
            [
                CouncilVote("User Advocate", "A", "r", 8),
                CouncilVote("Technical Lead", "A", "r", 8),
                CouncilVote("Product Strategist", "A", "r", 8),
            ]
        )
        council = self._wire_council(
            phase,
            round_results=[consensus],
            diversified_result=None,
        )

        result = await phase._run_council_vote(sample_task, conv, "directions text")

        assert result == 1
        assert council.vote.await_count == 1
        council.mediate.assert_not_called()
        council.vote_diversified.assert_not_called()

    @pytest.mark.asyncio
    async def test_round_2_consensus_skips_round_3(
        self,
        phase: ShapePhase,
        sample_task: Task,
        conv: ShapeConversation,
        deps: dict,
    ) -> None:
        """If round 2 converges, the diversified panel does NOT run — round 3
        is gated on a split after round 2, not on every council invocation."""
        round_2_consensus = CouncilResult(
            [
                CouncilVote("User Advocate", "B", "r", 7),
                CouncilVote("Technical Lead", "B", "r", 7),
                CouncilVote("Product Strategist", "A", "r", 6),
            ]
        )
        council = self._wire_council(
            phase,
            round_results=[_make_split_result(), round_2_consensus],
            diversified_result=None,
        )

        result = await phase._run_council_vote(sample_task, conv, "directions text")

        assert result == 1
        assert council.vote.await_count == 2
        council.mediate.assert_awaited_once()
        council.vote_diversified.assert_not_called()

    @pytest.mark.asyncio
    async def test_round_3_publishes_diversified_event(
        self,
        phase: ShapePhase,
        sample_task: Task,
        conv: ShapeConversation,
        deps: dict,
    ) -> None:
        """The diversified-round activation must be observable via the event
        bus so the audit JSONL can attribute W4 outcomes (per ADR-0063
        measurability section)."""
        diversified = _make_consensus_result("B")
        self._wire_council(
            phase,
            round_results=[_make_split_result(), _make_split_result()],
            diversified_result=diversified,
        )

        await phase._run_council_vote(sample_task, conv, "directions text")

        published_actions = [
            call.args[0].data.get("action")
            for call in deps["event_bus"].publish.await_args_list
        ]
        assert "council_diversified_round" in published_actions
