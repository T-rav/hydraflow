"""Tests for the shape phase — product direction selection."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import HydraFlowConfig
from expert_council import CouncilResult, CouncilVote
from models import ShapeConversation, ShapeTurnResult, Task
from shape_phase import _SHAPE_OPTIONS_MARKER, ShapePhase
from state import StateTracker


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


# ---------------------------------------------------------------------------
# Convergence ledger recording (Task 3)
# ---------------------------------------------------------------------------


def _make_shape_phase_with_real_state(
    tmp_path: Path,
    *,
    convergence_gate_enabled: bool,
    shape_runner: MagicMock | None = None,
) -> tuple[ShapePhase, StateTracker]:
    """Build a ShapePhase backed by a real StateTracker for ledger assertions."""
    from events import EventBus

    cfg = HydraFlowConfig(
        repo="test/repo",
        state_file=tmp_path / "state.json",
        convergence_gate_enabled=convergence_gate_enabled,
    )
    state = StateTracker(cfg.state_file)
    bus = EventBus()
    store = MagicMock()
    prs = AsyncMock()
    stop_event = asyncio.Event()
    phase = ShapePhase(
        cfg,
        state,
        store,
        prs,
        bus,
        stop_event,
        shape_runner=shape_runner,
    )
    return phase, state


class TestShapeConvergenceLedger:
    """Shape phase records boundary verdicts into the ConvergenceLedger (Task 3)."""

    @pytest.mark.asyncio
    async def test_selection_made_records_advance_verdict(self, tmp_path: Path) -> None:
        """Gate ON + selection found in comments -> ledger records 'ADVANCE'."""
        phase, state = _make_shape_phase_with_real_state(
            tmp_path, convergence_gate_enabled=True
        )
        task = Task(id=55, title="Build notifications", body="", labels=[])
        comments = [
            f"{_SHAPE_OPTIONS_MARKER} for #55\n\n### Direction A: ...",
            "Direction A — let's go with this",
        ]
        phase._store.enrich_with_comments = AsyncMock(
            return_value=task.model_copy(update={"comments": comments})
        )

        await phase._shape_single(task)

        ledger = state.get_convergence_ledger(55)
        assert ledger is not None, "Ledger must be created when gate is on"
        assert ledger.stage_state["shape"].last_verdict == "ADVANCE"

    @pytest.mark.asyncio
    async def test_waiting_records_loop_back_verdict(self, tmp_path: Path) -> None:
        """Gate ON + no selection found (still waiting) -> ledger records 'LOOP_BACK'."""
        phase, state = _make_shape_phase_with_real_state(
            tmp_path, convergence_gate_enabled=True
        )
        task = Task(id=56, title="Build search", body="", labels=[])
        comments = [
            f"{_SHAPE_OPTIONS_MARKER} for #56\n\n### Direction A: ...",
            "Hmm, not sure yet...",
        ]
        phase._store.enrich_with_comments = AsyncMock(
            return_value=task.model_copy(update={"comments": comments})
        )

        await phase._shape_single(task)

        ledger = state.get_convergence_ledger(56)
        assert ledger is not None, "Ledger must be created when gate is on"
        assert ledger.stage_state["shape"].last_verdict == "LOOP_BACK"

    @pytest.mark.asyncio
    async def test_runner_finalized_records_advance_verdict(
        self, tmp_path: Path
    ) -> None:
        """Gate ON + runner returns is_final=True -> ledger records 'ADVANCE'."""
        runner = MagicMock()
        runner.bind_escalation_deps = MagicMock()
        runner.run_turn = AsyncMock(
            return_value=ShapeTurnResult(content="Final direction", is_final=True)
        )
        phase, state = _make_shape_phase_with_real_state(
            tmp_path, convergence_gate_enabled=True, shape_runner=runner
        )
        task = Task(id=57, title="Build analytics", body="", labels=[])
        # No options marker → goes into _shape_with_runner path
        phase._store.enrich_with_comments = AsyncMock(
            return_value=task.model_copy(update={"comments": []})
        )
        # conv has no turns, so _handle_waiting_state returns proceed=True immediately
        phase._state.get_shape_conversation = MagicMock(return_value=None)
        phase._state.set_shape_conversation = MagicMock()
        phase._state.increment_session_counter = MagicMock()
        # _handle_waiting_state: conv has no turns, so proceed=True immediately
        phase._prs.transition = AsyncMock()
        phase._prs.post_comment = AsyncMock()

        # _process_finalization calls post_comment + transition + increment
        await phase._shape_with_runner(task)

        ledger = state.get_convergence_ledger(57)
        assert ledger is not None, "Ledger must be created when gate is on"
        assert ledger.stage_state["shape"].last_verdict == "ADVANCE"

    @pytest.mark.asyncio
    async def test_gate_off_records_no_ledger_on_selection(
        self, tmp_path: Path
    ) -> None:
        """Gate OFF -> no ledger created even when selection is found."""
        phase, state = _make_shape_phase_with_real_state(
            tmp_path, convergence_gate_enabled=False
        )
        task = Task(id=58, title="Improve onboarding", body="", labels=[])
        comments = [
            f"{_SHAPE_OPTIONS_MARKER} for #58\n\n### Direction A: ...",
            "Direction B please",
        ]
        phase._store.enrich_with_comments = AsyncMock(
            return_value=task.model_copy(update={"comments": comments})
        )

        await phase._shape_single(task)

        ledger = state.get_convergence_ledger(58)
        assert ledger is None, "No ledger should be created when gate is off"

    @pytest.mark.asyncio
    async def test_runner_finalized_with_concerns_records_signatures(
        self, tmp_path: Path
    ) -> None:
        """Gate ON + adversarial agents with HIGH concerns -> signatures recorded."""
        from datetime import datetime

        from pending_concerns import AdversarialState, Concern

        runner = MagicMock()
        runner.bind_escalation_deps = MagicMock()
        runner.run_turn = AsyncMock(
            return_value=ShapeTurnResult(content="Final content", is_final=True)
        )
        phase, state = _make_shape_phase_with_real_state(
            tmp_path, convergence_gate_enabled=True, shape_runner=runner
        )
        task = Task(id=59, title="Build API gateway", body="", labels=[])
        phase._store.enrich_with_comments = AsyncMock(
            return_value=task.model_copy(update={"comments": []})
        )
        phase._state.get_shape_conversation = MagicMock(return_value=None)
        phase._state.set_shape_conversation = MagicMock()
        phase._state.increment_session_counter = MagicMock()
        phase._prs.transition = AsyncMock()
        phase._prs.post_comment = AsyncMock()

        # Plant an adversarial state with a HIGH concern via state
        concern = Concern(
            id="c1",
            raised_in_phase="shape",
            raised_in_stage="shape_challenger",
            severity="HIGH",
            concern="Security risk in API design",
            raised_at=datetime.now(),
            must_address_by="plan",
        )
        adv = AdversarialState(phase="shape", pending_concerns=[concern])
        # Wire adversarial agents so the block runs, then override get_adversarial_state
        mock_challenger = MagicMock()
        phase._challenger_agent = mock_challenger
        phase._state.get_adversarial_state = MagicMock(return_value=adv)
        phase._state.set_adversarial_state = MagicMock()

        # Override _run_shape_challenger to do nothing (concern already in adv)
        phase._run_shape_challenger = AsyncMock()

        await phase._shape_with_runner(task)

        ledger = state.get_convergence_ledger(59)
        assert ledger is not None
        assert ledger.stage_state["shape"].last_verdict == "ADVANCE"
        assert (
            "Security risk in API design"
            in ledger.stage_state["shape"].last_finding_signatures
        )
